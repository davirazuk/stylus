#!/usr/bin/env python3
"""STYLUS — vinyl ritual, rebuilt standalone. Not a scope reskin.

Standalone turntable app: real plinth, real disc, real needle.
Scope is phosphor (additive, bloom, scanline). Vinyl is wood+plastic
(forward, Phong, soft shadow). No shared shaders, no shared FBO.
"""
import argparse, math, os, time, subprocess, threading, json
import numpy as np, pygame
from OpenGL.GL import *
try:
    import pyaudio
except: pyaudio=None
try:
    import vinyl
except Exception as _e:
    vinyl=None; _VINYL_ERR=_e

# ── constants ──
RITUAL_CX, RITUAL_CY, RITUAL_R = -0.08, -0.06, 0.72
RATE, BLOCK, TRACE_N = 44100, 512, 760

# ── shaders: vinyl material, not phosphor ──
VINYL_VS = """
#version 330
layout(location=0) in vec2 pos;
layout(location=1) in vec4 col;
layout(location=2) in float edge;
out vec4 vcol; out float vedge;
void main(){ vcol=col; vedge=edge; gl_Position=vec4(pos,0,1); }
"""
VINYL_FS = """
#version 330
in vec4 vcol; in float vedge; out vec4 frag;
void main(){
    float d=abs(vedge);
    float a=1.0 - smoothstep(0.46,1.0,d);
    a *= 0.94 + 0.06*exp(-d*d*9.0);
    vec3 col=vcol.rgb*a;
    float br=dot(col, vec3(0.299,0.587,0.114));
    // Warm bloom — bright grooves glow amber, not just brighter grey
    if(br>0.18){
        float bloom=pow((br-0.18)/0.82, 1.3)*0.30;
        bloom*=1.0-smoothstep(0.0,1.0,d)*0.45;
        col+=vec3(bloom)*vec3(1.0,0.72,0.38);
    }
    frag=vec4(col, 1.0);
}
"""
PLINTH_FS = """
#version 330
in vec2 uv; out vec4 frag;
uniform vec2 u_res;
uniform float u_time;
void main(){
    vec2 p = uv*2.0-1.0;
    // Dark surface — matte, round
    float g1 = sin(p.x*18.0 + p.y*2.0)*0.5+0.5;
    float g2 = sin(p.x*42.0 - p.y*7.0)*0.5+0.5;
    float grain = mix(g1, g2, 0.35) * 0.012;
    vec3 surface = vec3(0.018,0.016,0.022) + vec3(grain);
    // Subtle circular surface under disc
    float surfDist = length(p - vec2(-0.08, -0.06));
    surface *= 1.0 + smoothstep(0.9, 0.3, surfDist) * 0.08;
    float vig = 1.0 - dot(p,p)*0.16;
    vig = pow(vig, 0.92);
    // warm highlight top-left
    float hl = max(0.0, dot(normalize(vec2(-0.6,0.5)), p)) * 0.04;
    hl *= (1.0 - length(p)*0.4);
    vec3 col = surface*vig + vec3(hl*0.9, hl*0.7, hl*0.5);
    // warm disc glow
    float disc = length(p - vec2(-0.08, -0.06));
    col += vec3(0.12, 0.07, 0.03) * exp(-disc*disc*4.0) * 0.18;
    // Floating dust particles
    for(int i=0; i<6; i++){
        float fi = float(i);
        vec2 offs = vec2(
            sin(u_time*0.06+fi*2.3)*0.5-0.08,
            cos(u_time*0.04+fi*3.1)*0.4-0.06
        );
        float dust = exp(-length(p-offs)*120.0)*0.08;
        float twinkle = 0.5+0.5*sin(u_time*1.1+fi*4.7);
        col += vec3(0.06,0.055,0.05)*dust*twinkle;
    }
    frag = vec4(col, 1.0);
}
"""
TEXT_VS = """
#version 330
layout(location=0) in vec2 pos; layout(location=1) in vec2 uv; out vec2 vuv;
void main(){ vuv=uv; gl_Position=vec4(pos,0,1); }
"""
TEXT_FS = """
#version 330
in vec2 vuv; out vec4 frag; uniform sampler2D tex; uniform vec4 tint;
void main(){ vec4 t=texture(tex,vuv); frag=vec4(tint.rgb, t.a*tint.a); }
"""
LABEL_FS = """
#version 330
in vec2 vuv; out vec4 frag; uniform sampler2D tex; uniform float alpha;
void main(){ vec4 t=texture(tex,vuv); frag=vec4(t.rgb, t.a*alpha); }
"""

def compile_shader(vs,fs):
    p=glCreateProgram()
    for s,k in ((vs,GL_VERTEX_SHADER),(fs,GL_FRAGMENT_SHADER)):
        sh=glCreateShader(k); glShaderSource(sh,s); glCompileShader(sh)
        if not glGetShaderiv(sh,GL_COMPILE_STATUS): raise RuntimeError(glGetShaderInfoLog(sh).decode())
        glAttachShader(p,sh); glDeleteShader(sh)
    glLinkProgram(p)
    if not glGetProgramiv(p,GL_LINK_STATUS): raise RuntimeError(glGetProgramInfoLog(p).decode())
    return p

def make_quad():
    vao=glGenVertexArrays(1); vbo=glGenBuffers(1)
    verts=np.array([-1,-1,1,-1,-1,1,1,1],dtype=np.float32)
    glBindVertexArray(vao); glBindBuffer(GL_ARRAY_BUFFER,vbo)
    glBufferData(GL_ARRAY_BUFFER, verts.nbytes, verts, GL_STATIC_DRAW)
    glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,0,None); glEnableVertexAttribArray(0)
    glBindVertexArray(0); return vao

# ── audio + deck same as before but distinct GL ──
class OnePoleLPF:
    def __init__(self,cut,rate,ch=2):
        rc=1/(2*math.pi*cut); dt=1/rate; self.alpha=dt/(rc+dt); self.y=np.zeros(ch,dtype=np.float64)
    def apply(self,blk):
        out=np.empty_like(blk,dtype=np.float64); y=self.y; a=self.alpha
        for i in range(len(blk)):
            y=y+a*(blk[i].astype(np.float64)-y); out[i]=y
        self.y=y; return out.astype(np.float32)

class AudioCapture:
    def __init__(self, src):
        import time, threading, collections, re, subprocess
        if pyaudio is None: raise SystemExit(3)
        self.rate=44100
        try:
            out=subprocess.run(["pw-metadata","-n","settings"],capture_output=True,text=True,timeout=2).stdout
            m=re.search(r"key:'clock\.rate'\s+value:'(\d+)'",out)
            if m: self.rate=int(m.group(1))
        except: pass
        self.buf=np.zeros((TRACE_N,2),dtype=np.float32)
        self._lpf=OnePoleLPF(900,self.rate); self._bass=OnePoleLPF(150,self.rate,1); self._mid=OnePoleLPF(2500,self.rate,1)
        self.level_l=self.level_r=self.bass=self.treble=0.0
        self._stop=False; self._lock=threading.Lock()
        os.environ["PULSE_SOURCE"]=src or ""
        self.p=pyaudio.PyAudio()
        dev=None
        for i in range(self.p.get_device_count()):
            inf=self.p.get_device_info_by_index(i)
            if inf["name"]=="pulse" and inf["maxInputChannels"]>0: dev=i; break
        self.stream=self.p.open(format=pyaudio.paInt16,channels=2,rate=self.rate,input=True,input_device_index=dev,frames_per_buffer=BLOCK)
        threading.Thread(target=self._run,daemon=True).start()
    def _run(self):
        import time, numpy as np
        while not self._stop:
            try: data=self.stream.read(BLOCK,exception_on_overflow=False)
            except: continue
            raw=np.frombuffer(data,dtype=np.int16).reshape(-1,2).astype(np.float32)/32768.0
            filt=self._lpf.apply(raw)
            b=np.abs(filt[:,0]+filt[:,1])*0.5; m=np.abs(filt[:,0]-filt[:,1])*0.5
            bv=float(self._bass.apply(b.reshape(-1,1)).mean()); mv=float(self._mid.apply(m.reshape(-1,1)).mean())
            with self._lock:
                self.buf=filt[-TRACE_N:].copy()
                self.level_l=float((raw[:,0]**2).mean()**0.5); self.level_r=float((raw[:,1]**2).mean()**0.5)
                self.bass=bv*16; self.treble=mv*26
    def snapshot(self):
        with self._lock: return self.buf.copy()
    def close(self):
        self._stop=True
        try: self.stream.stop_stream(); self.stream.close(); self.p.terminate()
        except: pass

def find_monitor():
    f=os.environ.get("STYLUS_DECK_SOURCE")
    if f: return f
    try:
        out=subprocess.run(["pactl","list","sources","short"],capture_output=True,text=True,timeout=2).stdout
        ls=[l for l in out.splitlines() if ".monitor" in l]
        for l in ls:
            if "RUNNING" in l: return l.split()[1]
        if ls: return ls[0].split()[1]
    except: pass
    return None

# ── text/label helpers (minimal) ──
class TextOSD:
    def __init__(self,anchor="bottom-left",hold=2,fade=0.7,persist=False,sz=30):
        pygame.font.init()
        try: self.font=pygame.font.SysFont("dejavusansmono,monospace",sz)
        except: self.font=pygame.font.Font(None,sz+4)
        self.anchor=anchor; self.hold=hold; self.fade=fade; self.persist=persist
        self.tex=glGenTextures(1); self.vao=glGenVertexArrays(1); self.vbo=glGenBuffers(1)
        glBindVertexArray(self.vao); glBindBuffer(GL_ARRAY_BUFFER,self.vbo)
        glBufferData(GL_ARRAY_BUFFER,6*4*4,None,GL_DYNAMIC_DRAW)
        glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,16,ctypes.c_void_p(0)); glEnableVertexAttribArray(0)
        glVertexAttribPointer(1,2,GL_FLOAT,GL_FALSE,16,ctypes.c_void_p(8)); glEnableVertexAttribArray(1)
        glBindVertexArray(0); self._text=None; self._surfs={}; self._t0=0; self.w=0
    def set_text(self,t,W,H):
        self._text=t; self._t0=time.monotonic(); self._surfs={}; self.w=0
        if t:
            s=self.font.render(t,True,(255,255,255)); self._surfs[W]=s; self.w=s.get_width()
    def alpha(self):
        if self._text is None: return 0
        a=time.monotonic()-self._t0
        if self.persist: return 1
        if a<self.hold: return 1
        fa=a-self.hold
        return 0 if fa>self.fade else max(0,1-fa/self.fade)
    def draw(self,prog,col):
        a=self.alpha()
        if a<=0 or self._text is None: return
        W,H=pygame.display.get_surface().get_size()
        surf=self._surfs.get(W)
        if surf is None:
            surf=self.font.render(self._text,True,(255,255,255)); self._surfs[W]=surf
        rw,rh=surf.get_size(); tex_data=pygame.image.tostring(surf,"RGBA",False)
        glBindTexture(GL_TEXTURE_2D,self.tex)
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR); glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR)
        glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA,rw,rh,0,GL_RGBA,GL_UNSIGNED_BYTE,tex_data)
        m=40
        if "center" in self.anchor:
            x0=W-rw-m if "right" in self.anchor else (m if "left" in self.anchor else (W-rw)//2)
            y0=(H-rh)//2
        else:
            x0=W-rw-m if "right" in self.anchor else m
            y0=m if "top" in self.anchor else H-rh-m
        def px(x,y): return (x/W*2-1,1-y/H*2)
        p0=px(x0,y0); p1=px(x0+rw,y0); p2=px(x0+rw,y0+rh); p3=px(x0,y0+rh)
        # v=0 nos vértices de CIMA da tela: com tostring(...,False) a linha 0
        # da memória é o topo da surface, e o GL trata a linha 0 como v=0 —
        # então topo↔v=0. Conferido desenhando com o driver offscreen do SDL:
        # o par (False + v=1 em cima) que esteve aqui (e o (True + v=0) de
        # antes) desenhava o texto da faixa de CABEÇA PARA BAIXO — os dois
        # são a mesma inversão dupla. Sintoma visível: título do disco
        # espelhado em pé no OSD.
        arr=np.array([*p0,0,0,*p1,1,0,*p2,1,1,*p0,0,0,*p2,1,1,*p3,0,1],dtype=np.float32)
        r,g,b=col
        glUniform1i(glGetUniformLocation(prog,"tex"),0)
        glUniform4f(glGetUniformLocation(prog,"tint"),r*a*1.8,g*a*1.8,b*a*1.8,a)
        glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D,self.tex)
        glBindVertexArray(self.vao); glBindBuffer(GL_ARRAY_BUFFER,self.vbo)
        import ctypes; glBufferSubData(GL_ARRAY_BUFFER,0,arr.nbytes,arr)
        glDrawArrays(GL_TRIANGLES,0,6); glBindVertexArray(0)

class RecordLabel:
    def __init__(self):
        self.tex=glGenTextures(1); self.vao=glGenVertexArrays(1); self.vbo=glGenBuffers(1)
        glBindVertexArray(self.vao); glBindBuffer(GL_ARRAY_BUFFER,self.vbo)
        glBufferData(GL_ARRAY_BUFFER,6*4*4,None,GL_DYNAMIC_DRAW)
        glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,16,ctypes.c_void_p(0)); glEnableVertexAttribArray(0)
        glVertexAttribPointer(1,2,GL_FLOAT,GL_FALSE,16,ctypes.c_void_p(8)); glEnableVertexAttribArray(1)
        glBindVertexArray(0); self.source="\x00"; self.ok=False
    def load(self,path):
        if path==self.source: return
        self.source=path; self.ok=False
        if not path or not os.path.isfile(path): return
        try:
            from PIL import Image
            n=512; im=Image.open(path).convert("RGBA").resize((n,n),Image.LANCZOS)
            import numpy as np
            a=np.asarray(im).astype(np.float32).copy()
            yy,xx=np.mgrid[0:n,0:n]; rad=np.hypot(xx-(n-1)/2,yy-(n-1)/2)/((n-1)/2)
            a[...,3]*=np.clip((1-rad)*(n*0.25),0,1)
            hole=vinyl.R_SPINDLE/vinyl.R_LABEL
            a[...,3]*=np.clip((rad-hole)*(n*0.25),0,1)
            data=a.clip(0,255).astype(np.uint8).tobytes()
            glBindTexture(GL_TEXTURE_2D,self.tex)
            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR); glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR)
            glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA,n,n,0,GL_RGBA,GL_UNSIGNED_BYTE,data); self.ok=True
        except Exception as e: print(f"ritual: capa não carregou: {e}"); self.ok=False
    def draw(self,prog,rot,iso,alpha=1):
        if not self.ok: return
        r=vinyl.R_LABEL*0.72; import math
        c,sn=math.cos(rot),math.sin(rot); corners=[(-1,-1),(1,-1),(1,1),(-1,1)]
        arr=np.empty((4,4),dtype=np.float32)
        for i,(u,v) in enumerate(corners):
            x=(u*c - v*sn)*r*iso[0] + RITUAL_CX; y=(u*sn + v*c)*r*iso[1] + RITUAL_CY
            arr[i]=[x,y, u*0.5+0.5, v*0.5+0.5]
        quad=np.array([*arr[0],*arr[1],*arr[2], *arr[0],*arr[2],*arr[3]],dtype=np.float32)
        glUseProgram(prog); glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D,self.tex)
        glUniform1i(glGetUniformLocation(prog,"tex"),0); glUniform1f(glGetUniformLocation(prog,"alpha"),alpha)
        glBindVertexArray(self.vao); glBindBuffer(GL_ARRAY_BUFFER,self.vbo)
        glBufferSubData(GL_ARRAY_BUFFER,0,quad.nbytes,quad); glDrawArrays(GL_TRIANGLES,0,6); glBindVertexArray(0)

# ── ribbon helpers (forward, not phosphor) ──
def build_strip(pts, half_w, W,H, cols):
    import numpy as np
    n=len(pts)
    if n<2: return np.zeros((0,7),dtype=np.float32)
    scale=np.array([W/2,H/2],dtype=np.float64)
    px=pts.astype(np.float64)*scale
    tan=np.zeros_like(px); tan[1:-1]=px[2:]-px[:-2]; tan[0]=px[1]-px[0]; tan[-1]=px[-1]-px[-2]
    l=np.hypot(tan[:,0],tan[:,1]); l[l<1e-6]=1; tan/=l[:,None]
    nrm=np.stack([-tan[:,1],tan[:,0]],axis=1)
    hw=np.asarray(half_w,dtype=np.float64)
    if hw.ndim==0: hw=np.full(n,float(hw))
    off=nrm*hw[:,None]
    left=(px+off)/scale; right=(px-off)/scale
    out=np.empty((2*n,7),dtype=np.float32)
    out[0::2,0:2]=left; out[1::2,0:2]=right
    out[0::2,2:6]=cols; out[1::2,2:6]=cols
    out[0::2,6]=1; out[1::2,6]=-1
    return out

def build_segs(pairs, half_w, W,H, cols):
    import numpy as np
    k=len(pairs)//2
    if k<1: return np.zeros((0,7),dtype=np.float32)
    scale=np.array([W/2,H/2],dtype=np.float64)
    px=pairs.astype(np.float64)*scale; a=px[0::2]; b=px[1::2]; d=b-a; l=np.hypot(d[:,0],d[:,1]); l[l<1e-6]=1; tan=d/l[:,None]; nrm=np.stack([-tan[:,1],tan[:,0]],axis=1); off=nrm*half_w
    a0=(a+off)/scale; a1=(a-off)/scale; b0=(b+off)/scale; b1=(b-off)/scale
    out=np.empty((k*6,7),dtype=np.float32)
    out[0::6,0:2]=a0; out[1::6,0:2]=a1; out[2::6,0:2]=b0; out[3::6,0:2]=a1; out[4::6,0:2]=b1; out[5::6,0:2]=b0
    arr=np.asarray(cols,dtype=np.float32); out[:,2:6]=np.repeat(arr,6,axis=0) if arr.ndim==2 else arr
    out[0::6,6]=1; out[1::6,6]=-1; out[2::6,6]=1; out[3::6,6]=-1; out[4::6,6]=-1; out[5::6,6]=1
    return out

# ── scene ──
class RitualScene:
    def __init__(self, view=False):
        self.view=view; self.session=vinyl.Session(); self.deck=vinyl.Deck()
        if view: self.deck.phase=vinyl.PLAY; self.deck.speed=vinyl.REV_PER_SEC
        self.album=None; self._key=None; self._resolving=False; self._side=None; self._was_paused=False; self._rearm=False; self._ended=False; self._last_phase=None; self._banner=None; self._banner_until=0; self._last_t_abs=0; self._ti_cache=[None,0]
    def close(self):
        try: self.session.close()
        except: pass
    def _resolve(self,snap):
        try:
            f=vinyl.resolve_album(snap.get("path"),snap.get("artist",""),snap.get("album",""))
            self.album=vinyl.Album(f) if f else None
            if self.album: print(f"record: {self.album.artist} — {self.album.name}"); self._rearm=True
        except Exception as e: self.album=None; print(f"record: {e}")
        finally: self._resolving=False
    def update(self,dt):
        snap=self.session.snapshot()
        _path=snap.get("path") or ""; _folder=os.path.dirname(_path) if _path else ""
        key=(_folder,snap.get("artist"),snap.get("album"))
        if key!=self._key and not self._resolving and any(key):
            self._key=key; self._resolving=True; threading.Thread(target=self._resolve,args=(snap,),daemon=True).start()
        if self._rearm:
            self._rearm=False; self._side=None; self._ended=False
            if self.view:
                self.deck.phase=vinyl.PLAY; self.deck.speed=vinyl.REV_PER_SEC; self.deck.t0=time.monotonic()
            else:
                self.deck.after_lift=vinyl.BREAK; self.deck.go(vinyl.SPINUP)
        paused=bool(snap.get("paused",True))
        if self.album and self.album.total:
            pos,_=self.session.position(); ti=vinyl.track_index_for(self.album,snap,self._ti_cache)
            if 0<=ti<len(self.album.tracks):
                t_abs=self.album.album_time(ti,pos); idx, side=self.album.side_for(t_abs)
                if side:
                    if self._side is None: self._side=idx
                    elif idx!=self._side:
                        self._side=idx
                        if self.deck.phase==vinyl.PLAY:
                            self.deck.after_lift=vinyl.BREAK; self.deck.go(vinyl.LIFT); self.session.pause(True)
                self._last_t_abs=t_abs
                if not self._ended and self.deck.phase==vinyl.PLAY and t_abs>=self.album.total-0.4:
                    self._ended=True; self.deck.after_lift=vinyl.STOP; self.deck.go(vinyl.LIFT)
            elif not self._ended and self.deck.phase==vinyl.PLAY:
                self._ended=True; self.deck.after_lift=vinyl.STOP; self.deck.go(vinyl.LIFT)
        if self._was_paused and not paused and self.deck.phase==vinyl.BREAK:
            self.deck.go(vinyl.RETURN)
        return self._finish(dt,snap,paused)
    def _finish(self,dt,snap,paused):
        self._was_paused=paused; phase=self.deck.update(dt,playing=not paused)
        if not self.view and snap.get("source")=="mpv":
            down=(phase==vinyl.PLAY and self.deck.arm_lift()<0.12)
            if down and paused and self._last_phase==vinyl.DROP: self.session.pause(False)
            elif not down and not paused and phase in (vinyl.SPINUP,vinyl.CUE,vinyl.DROP,vinyl.LIFT,vinyl.BREAK,vinyl.STOP,vinyl.RETURN):
                self.session.pause(True)
        if phase==vinyl.PLAY and self._last_phase==vinyl.DROP:
            try:
                n=vinyl.log_play(self.album.folder,self.album.artist,self.album.name)
                self.album.plays=n; self._banner=vinyl.play_banner(n,self.album.first_played,f"{self.album.artist} — {self.album.name}"); self._banner_until=time.monotonic()+7
            except: pass
        self._last_phase=phase; return snap
    def build(self,snap,buf,W,H,iso):
        al=self.album
        if al is None or not al.total or snap is None: return [],None
        cx,cy,radius=RITUAL_CX,RITUAL_CY,RITUAL_R; light=math.radians(-38); rot=self.deck.rotation
        pos,_=self.session.position(); ti=vinyl.track_index_for(al,snap,self._ti_cache)
        t_abs=al.album_time(ti,pos); si,side=al.side_for(t_abs)
        if side is None: return [],None
        span=max(1e-6,side["end"]-side["start"]); frac=float(np.clip((t_abs-side["start"])/span,0,1))
        strips=[v for v in vinyl.disc_body(cx,cy,radius,iso,light)]
        # Disc shadow — dark ring behind disc for depth
        n_sh = 48
        sh_thetas = np.linspace(0, 2 * np.pi, n_sh, endpoint=False)
        sh_x = cx + np.cos(sh_thetas) * radius * 1.04
        sh_y = cy + np.sin(sh_thetas) * radius * 1.04 * iso[1]
        sh_pts = np.column_stack([sh_x, sh_y])
        sh_cols = np.full((n_sh, 4), [0.015, 0.01, 0.008, 1.0], dtype=np.float32)
        strips.insert(0, build_strip(sh_pts, 0.025 * radius, W, H, sh_cols))
        # Disc glow ring — warm light bleeding from edge
        n_glow = 48
        glow_thetas = np.linspace(0, 2 * np.pi, n_glow, endpoint=False)
        glow_inner = radius * 0.98
        glow_outer = radius * 1.08
        glow_x_in = cx + np.cos(glow_thetas) * glow_inner
        glow_y_in = cy + np.sin(glow_thetas) * glow_inner * iso[1]
        glow_x_out = cx + np.cos(glow_thetas) * glow_outer
        glow_y_out = cy + np.sin(glow_thetas) * glow_outer * iso[1]
        glow_pts = np.column_stack([glow_x_in, glow_y_in])
        glow_cols = np.column_stack([
            np.full(n_glow, 0.96 * 0.04),
            np.full(n_glow, 0.56 * 0.04),
            np.full(n_glow, 0.13 * 0.04),
            np.ones(n_glow)
        ]).astype(np.float32)
        strips.insert(1, build_strip(glow_pts, 0.035 * radius, W, H, glow_cols))
        # Void rings — faint concentric circles in the dark (matching phone)
        import random as _rnd
        _vrng = _rnd.Random(42)
        for vr in range(3):
            vr_r = radius * (1.15 + vr * 0.08)
            vr_n = 64
            vr_thetas = np.linspace(0, 2 * np.pi, vr_n, endpoint=False)
            vr_x = cx + np.cos(vr_thetas) * vr_r
            vr_y = cy + np.sin(vr_thetas) * vr_r * iso[1]
            vr_pts = np.column_stack([vr_x, vr_y])
            vr_a = 0.015 - vr * 0.004
            vr_cols = np.full((vr_n, 4), [0.04, 0.035, 0.05, vr_a], dtype=np.float32)
            strips.insert(2 + vr, build_strip(vr_pts, 0.008 * radius, W, H, vr_cols))
        # Ambient dust — floating particles in the void (matching phone)
        _dust_t = time.time()
        for di in range(6):
            dx = cx + math.sin(_dust_t * 0.07 + di * 2.1) * radius * 0.4
            dy = cy + math.cos(_dust_t * 0.05 + di * 3.7) * radius * 0.3
            dtwinkle = 0.5 + 0.5 * math.sin(_dust_t * 1.3 + di * 5.3)
            da = 0.12 * dtwinkle
            dp = np.array([[dx, dy]], dtype=np.float32)
            dc = np.array([[0.08, 0.07, 0.06, da]], dtype=np.float32)
            strips.append(build_strip(dp, 0.005 * radius, W, H, dc))
        tris=[]
        wm=vinyl.wear_marks(cx,cy,radius,iso,rot,seed=al.seed,plays=al.plays,crackle=self.deck.crackle)
        if wm is not None and len(wm[0]): tris.append(build_segs(wm[0],1.2,W,H,wm[1]))
        env=al.envelope_snapshot(); side_tracks=[al.tracks[i] for i in side.get("tracks",[])]
        played=int(frac*(vinyl.N_RINGS-1))
        for pts,cols,wd in vinyl.groove_rings(cx,cy,radius,iso,side,env,side_tracks,light,played_ring=played):
            strips.append(build_strip(pts,wd,W,H,cols))
        br=vinyl.boundary_ring(cx,cy,radius,iso,side,env,frac,light)
        if br: strips.append(build_strip(br[0],br[2],W,H,br[1]))
        if buf is not None and len(buf):
            mid=buf[:,0]+buf[:,1] if buf.ndim==2 else buf; sid=buf[:,0]-buf[:,1] if buf.ndim==2 else np.zeros_like(mid)
            lg=vinyl.live_groove(cx,cy,radius,iso,frac,mid,sid,rot)
            if lg: strips.append(build_strip(lg[0],lg[2],W,H,lg[1]))
        for pts,cols,wd in vinyl.edge_and_label_rings(cx,cy,radius,iso,light):
            strips.append(build_strip(pts,wd,W,H,cols))
        rest=vinyl.arm_rest(cx,cy,radius,iso)
        if rest is not None and len(rest[0]): tris.append(build_segs(rest[0],1.8,W,H,rest[1]))
        play_r=vinyl.R_PROG_OUT + (vinyl.R_PROG_IN - vinyl.R_PROG_OUT)*frac
        segs,cols,_=vinyl.tonearm(cx,cy,radius,iso,self.deck.arm_target_radius(play_r),lift=self.deck.arm_lift())
        if len(segs): tris.append(build_segs(segs,2.2,W,H,cols))
        # Laser beam — shoots from stylus tip into groove
        if self.deck.arm_lift() < 0.3:
            beam_fade = max(0.0, 1.0 - self.deck.arm_lift() * 3.3)
            beam_pulse = beam_fade * (0.6 + 0.4 * self.deck.crackle)
            _, (sx, sy) = vinyl.stylus_xy(cx, cy, radius, iso, self.deck.arm_target_radius(play_r), lift=self.deck.arm_lift())
            # Beam direction: radially inward from stylus
            to_cx, to_cy = cx - sx, cy - sy
            to_cl = math.hypot(to_cx, to_cy) or 1.0
            to_cx, to_cy = to_cx / to_cl, to_cy / to_cl
            beam_len = 0.06 * radius + 0.03 * self.deck.crackle * radius
            bx, by = sx + to_cx * beam_len, sy + to_cy * beam_len
            amber = (0.96 * beam_pulse, 0.56 * beam_pulse, 0.13 * beam_pulse)
            hot = (1.0 * beam_pulse, 0.92 * beam_pulse, 0.65 * beam_pulse)
            beam_segs = np.array([[sx, sy], [bx, by]], dtype=np.float32)
            beam_cols = np.array([[*amber, 1.0]], dtype=np.float32)
            tris.append(build_segs(beam_segs, 0.3, W, H, beam_cols))
            beam_segs2 = np.array([[sx, sy], [bx, by]], dtype=np.float32)
            beam_cols2 = np.array([[*hot, 1.0]], dtype=np.float32)
            tris.append(build_segs(beam_segs2, 0.08, W, H, beam_cols2))
            # Sparks — flickering dots at the impact point
            impact_fade = beam_fade
            now_t = time.time()
            for sk in range(4):
                t = now_t * 7.0 + sk * 1.7
                spark_x = bx + math.sin(t * 3.1) * 0.012 * radius * impact_fade
                spark_y = by + math.cos(t * 2.7) * 0.012 * radius * impact_fade
                spark_bright = impact_fade * (0.3 + 0.3 * math.sin(t * 5.0 + sk))
                spark_col = [[1.0 * spark_bright, 0.8 * spark_bright, 0.35 * spark_bright, 1.0]]
                # build_segs needs pairs of points; duplicate to make a tiny segment
                sp = np.array([[spark_x, spark_y], [spark_x, spark_y]], dtype=np.float32)
                sc = np.array(spark_col, dtype=np.float32)
                tris.append(build_segs(sp, 0.018, W, H, sc))
        arm=np.concatenate(tris,axis=0) if tris else None
        # ── progress ring — thin amber arc around disc showing side progress ──
        n_arc = 64
        arc_start = -math.pi / 2  # top of disc
        arc_end = arc_start + 2 * math.pi * frac
        arc_thetas = np.linspace(arc_start, arc_end, n_arc, endpoint=False)
        arc_r_inner = radius * 1.06
        arc_r_outer = radius * 1.08
        # inner points
        arc_x_in = cx + np.cos(arc_thetas) * arc_r_inner
        arc_y_in = cy + np.sin(arc_thetas) * arc_r_inner * iso[1]
        # outer points
        arc_x_out = cx + np.cos(arc_thetas) * arc_r_outer
        arc_y_out = cy + np.sin(arc_thetas) * arc_r_outer * iso[1]
        # interleave inner/outer for triangle strip
        arc_pts = np.zeros((n_arc * 2, 2), dtype=np.float32)
        arc_pts[0::2] = np.column_stack([arc_x_in, arc_y_in])
        arc_pts[1::2] = np.column_stack([arc_x_out, arc_y_out])
        # amber color, fading at the tail
        arc_cols = np.zeros((n_arc * 2, 4), dtype=np.float32)
        for ai in range(n_arc):
            fade = 1.0 - ai / n_arc
            bright = 0.7 + 0.3 * fade
            arc_cols[ai * 2] = [0.96 * bright, 0.56 * bright, 0.13 * bright, 0.9 * fade]
            arc_cols[ai * 2 + 1] = [0.96 * bright, 0.56 * bright, 0.13 * bright, 0.9 * fade]
        strips.append(build_strip(arc_pts, 0.004 * radius, W, H, arc_cols))
        # ── dim remainder ring (full circle, faint) ──
        rem_start = arc_end
        rem_end = arc_start + 2 * math.pi
        if rem_end > rem_start + 0.01:
            rem_n = max(16, n_arc - int(frac * n_arc))
            rem_thetas = np.linspace(rem_start, rem_end, rem_n, endpoint=False)
            rem_x_in = cx + np.cos(rem_thetas) * arc_r_inner
            rem_y_in = cy + np.sin(rem_thetas) * arc_r_inner * iso[1]
            rem_x_out = cx + np.cos(rem_thetas) * arc_r_outer
            rem_y_out = cy + np.sin(rem_thetas) * arc_r_outer * iso[1]
            rem_pts = np.zeros((rem_n * 2, 2), dtype=np.float32)
            rem_pts[0::2] = np.column_stack([rem_x_in, rem_y_in])
            rem_pts[1::2] = np.column_stack([rem_x_out, rem_y_out])
            rem_cols = np.full((rem_n * 2, 4), [0.04, 0.035, 0.03, 0.15], dtype=np.float32)
            strips.append(build_strip(rem_pts, 0.003 * radius, W, H, rem_cols))
        # ── power LED — small amber dot on plinth ──
        led_x = cx - radius * 1.35
        led_y = cy + radius * 0.85 * iso[1]
        led_pulse = 0.7 + 0.3 * math.sin(time.time() * 2.0)
        led_pts = np.array([[led_x, led_y]], dtype=np.float32)
        led_col = np.array([[0.96 * led_pulse, 0.56 * led_pulse, 0.13 * led_pulse, 0.9]], dtype=np.float32)
        strips.append(build_strip(led_pts, 0.012 * radius, W, H, led_col))
        # ── side label glow — faint "LADO A/B" position marker ──
        # small dot at the start of the current side's time range
        side_start_frac = 0.0
        if side:
            side_start_frac = (side["start"] / al.total) if al.total else 0
        marker_angle = arc_start + 2 * math.pi * side_start_frac
        mk_x = cx + math.cos(marker_angle) * radius * 1.03
        mk_y = cy + math.sin(marker_angle) * radius * 1.03 * iso[1]
        mk_pts = np.array([[mk_x, mk_y]], dtype=np.float32)
        mk_col = np.array([[0.96, 0.56, 0.13, 0.35]], dtype=np.float32)
        strips.append(build_strip(mk_pts, 0.008 * radius, W, H, mk_col))
        return strips, arm
    def banner(self):
        if self._banner and time.monotonic()<self._banner_until: return self._banner
        return None
    def caption_is_state(self): return self.deck.phase in (vinyl.BREAK,vinyl.STOP) or self.banner() is not None
    def current_lyric(self,snap):
        if self.album is None: return None
        idx=vinyl.track_index_for(self.album,snap,self._ti_cache)
        try: lines=self.album.lyrics_for(idx)
        except: return None
        if not lines: return None
        pos,_=self.session.position()
        lo,hi=0,len(lines)
        while lo<hi:
            mid=(lo+hi)//2
            if lines[mid][0]<=pos: lo=mid+1
            else: hi=mid
        if lo==0: return None
        return (lines[lo-1][1] or "").strip() or None

def main():
    if vinyl is None: print(f"ritual: { _VINYL_ERR}"); raise SystemExit(1)
    ap=argparse.ArgumentParser(); ap.add_argument("--res",default=None); ap.add_argument("--windowed",action="store_true"); ap.add_argument("--view",action="store_true",help="view only")
    args=ap.parse_args()
    pygame.display.init()
    if args.res: W,H=(int(v) for v in args.res.split("x"))
    else: info=pygame.display.Info(); W,H=info.current_w, info.current_h
    src=find_monitor(); print(f"monitor source: {src}")
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION,3); pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION,3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK,pygame.GL_CONTEXT_PROFILE_CORE)
    flags=pygame.OPENGL|pygame.DOUBLEBUF
    if not args.windowed: flags|=pygame.FULLSCREEN
    pygame.display.set_mode((W,H),flags); pygame.display.set_caption("STYLUS — ritual")
    prog_vinyl=compile_shader(VINYL_VS, VINYL_FS)
    prog_text=compile_shader(TEXT_VS, TEXT_FS)
    prog_label=compile_shader(TEXT_VS, LABEL_FS)
    prog_plinth=compile_shader("""#version 330
layout(location=0) in vec2 pos; out vec2 uv; void main(){ uv=pos*0.5+0.5; gl_Position=vec4(pos,0,1); }""",
"""#version 330
in vec2 uv; out vec4 frag;
uniform float u_time;
uniform vec2 u_res;
uniform float u_audio;
void main(){
  vec2 p=uv*2.0-1.0;
  float dd=length(p);
  // Deep void — matching phone aesthetic
  vec3 col=mix(vec3(0.010,0.011,0.018), vec3(0.004,0.004,0.006),
               smoothstep(0.0,1.2,dd));
  // Dark surface under disc
  float surface=smoothstep(0.92,0.60,dd)*0.12;
  col+=vec3(0.015,0.013,0.018)*surface;
  // Surface edge ring
  float edgeRing=smoothstep(0.03,0.0,abs(dd-0.78))*0.06;
  col+=vec3(0.04,0.035,0.05)*edgeRing;
  // Warm halo — breathes with audio (matching phone)
  float breathe=0.85+0.15*sin(u_time*0.4);
  float audioBloom=u_audio*0.18;
  col+=vec3(0.30,0.18,0.08)*exp(-dd*dd*3.2)*0.20*breathe*(1.0+audioBloom);
  col+=vec3(0.15,0.09,0.04)*exp(-dd*dd*1.0)*0.08*breathe*(1.0+audioBloom*0.6);
  // Ambient dust particles (matching phone)
  for(int i=0;i<5;i++){
    float fi=float(i);
    vec2 offs=vec2(
      sin(u_time*0.07+fi*2.1)*0.4,
      cos(u_time*0.05+fi*3.7)*0.3
    );
    float dust=exp(-length(p-offs)*80.0)*0.12;
    float twinkle=0.5+0.5*sin(u_time*1.3+fi*5.3);
    col+=vec3(0.08,0.07,0.06)*dust*twinkle;
  }
  // Vignette (matching phone)
  col*=1.0-dot(p,p)*0.32;
  // Film grain (matching phone)
  float n=fract(sin(dot(uv*2.3+u_time*0.007, vec2(12.9898,78.233)))*43758.5);
  col+=(n-0.5)*0.004;
  frag=vec4(col,1.0);
}""")
    quad=make_quad(); label=RecordLabel()
    # forward buffer, no bloom FBO
    r_vbo=glGenBuffers(1); r_vao=glGenVertexArrays(1)
    glBindVertexArray(r_vao); glBindBuffer(GL_ARRAY_BUFFER,r_vbo)
    glBufferData(GL_ARRAY_BUFFER,4*1024*1024,None,GL_DYNAMIC_DRAW)
    glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,28,ctypes.c_void_p(0)); glEnableVertexAttribArray(0)
    glVertexAttribPointer(1,4,GL_FLOAT,GL_FALSE,28,ctypes.c_void_p(8)); glEnableVertexAttribArray(1)
    glVertexAttribPointer(2,1,GL_FLOAT,GL_FALSE,28,ctypes.c_void_p(24)); glEnableVertexAttribArray(2)
    glBindVertexArray(0)
    osd=TextOSD(anchor="bottom-left"); mpris=TextOSD(anchor="bottom-right",hold=4,fade=1.2,sz=26); lyric=TextOSD(anchor="center-right",persist=True,sz=28)
    cap=AudioCapture(src); ritual=RitualScene(view=args.view)
    ISO=(min(1,H/W), min(1,W/H))
    t0=time.time(); clock=pygame.time.Clock(); running=True; prev=0
    while running:
        for ev in pygame.event.get():
            if ev.type==pygame.QUIT: running=False
            elif ev.type==pygame.KEYDOWN:
                if ev.key in (pygame.K_ESCAPE,pygame.K_q): running=False
                elif ev.key==pygame.K_SPACE: subprocess.Popen(["playerctl","play-pause"])
                elif ev.key==pygame.K_LEFT: subprocess.Popen(["playerctl","position","10-"])
                elif ev.key==pygame.K_RIGHT: subprocess.Popen(["playerctl","position","+10"])
                elif ev.key==pygame.K_n: subprocess.Popen(["playerctl","next"])
                elif ev.key==pygame.K_p: subprocess.Popen(["playerctl","previous"])
                elif ev.key==pygame.K_UP: subprocess.Popen(["pamixer","-i","5"])
                elif ev.key==pygame.K_DOWN: subprocess.Popen(["pamixer","-d","5"])
                elif ev.key in (pygame.K_PLUS,pygame.K_EQUALS): subprocess.Popen(["pamixer","-i","5"])
                elif ev.key in (pygame.K_MINUS,): subprocess.Popen(["pamixer","-d","5"])
                elif ev.key in (pygame.K_f,pygame.K_F11): pygame.display.toggle_fullscreen()
        elapsed=time.time()-t0; dt=max(0,elapsed-prev); prev=elapsed
        snap=ritual.update(dt); buf=cap.snapshot()
        strips,arm=ritual.build(snap,buf,W,H,ISO)
        # ── draw forward, no phosphor decay ──
        glViewport(0,0,W,H); glClearColor(0.003,0.003,0.006,1); glClear(GL_COLOR_BUFFER_BIT)
        # plinth quad behind — deep void, matching phone aesthetic
        glUseProgram(prog_plinth)
        glUniform1f(glGetUniformLocation(prog_plinth, "u_time"), elapsed)
        glUniform2f(glGetUniformLocation(prog_plinth, "u_res"), float(W), float(H))
        # audio level for reactive bloom
        audio_level = 0.0
        if cap is not None:
            try:
                audio_level = min(1.0, (cap.level_l + cap.level_r) * 0.5)
            except Exception:
                pass
        glUniform1f(glGetUniformLocation(prog_plinth, "u_audio"), audio_level)
        glBindVertexArray(quad); glDrawArrays(GL_TRIANGLE_STRIP,0,4)
        # vinyl strips + arm
        if strips:
            comb=np.concatenate(strips,axis=0) if strips else np.zeros((0,7),dtype=np.float32)
            if len(comb):
                glBindBuffer(GL_ARRAY_BUFFER,r_vbo); glBufferSubData(GL_ARRAY_BUFFER,0,comb.nbytes,comb)
                glUseProgram(prog_vinyl); glBindVertexArray(r_vao)
                off=0
                for st in strips:
                    if len(st): glDrawArrays(GL_TRIANGLE_STRIP,off,len(st)); off+=len(st)
            if arm is not None and len(arm):
                glBindBuffer(GL_ARRAY_BUFFER,r_vbo); glBufferSubData(GL_ARRAY_BUFFER,0,arm.nbytes,arm)
                glUseProgram(prog_vinyl); glBindVertexArray(r_vao); glDrawArrays(GL_TRIANGLES,0,len(arm))
        glBindVertexArray(0)
        # label + OSD
        if ritual.album and label:
            glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA)
            label.load(ritual.album.cover); label.draw(prog_label, ritual.deck.rotation, ISO)
            glDisable(GL_BLEND)
        # lyrics etc
        ly=ritual.current_lyric(snap)
        if ly != getattr(main,"_last_ly",None):
            lyric.set_text(ly,W,H); main._last_ly=ly
        glUseProgram(prog_text); glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA)
        osd.draw(prog_text,(1,1,1)); mpris.draw(prog_text,(1,1,1)); lyric.draw(prog_text,(1,1,1))
        glDisable(GL_BLEND)
        pygame.display.flip(); clock.tick(60)
    cap.close(); ritual.close(); pygame.quit()

if __name__=="__main__": main()
