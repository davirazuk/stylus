#include "tags.h"

#include <mpg123.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* nesta revisão do libmpg123, o texto do ID3v2 já chega em UTF-8 */
static void copy_str(const mpg123_string *s, char *out, size_t cap)
{
    if (!out || cap == 0) return;
    out[0] = '\0';
    if (!s || !s->p) return;
    size_t n = s->fill > 0 ? s->fill - 1 : 0; /* sem o zero final */
    if (n >= cap) n = cap - 1;
    memcpy(out, s->p, n);
    out[n] = '\0';
}

/* procura um campo textual (ex: "TRCK") na lista de campos ID3v2 e devolve o nº */
static int parse_track_no(const mpg123_id3v2 *v2, const char *id4)
{
    if (!v2->text) return -1;
    for (size_t i = 0; i < v2->texts; i++) {
        char f[5] = {0};
        memcpy(f, v2->text[i].id, 4);
        if (strcmp(f, id4) == 0) {
            const mpg123_string *t = &v2->text[i].text;
            if (t->p) {
                int num = 0, any = 0;
                const unsigned char *p = (const unsigned char *)t->p;
                for (size_t k = 0; k < (t->fill ? t->fill - 1 : 0) && p[k]; k++) {
                    if (p[k] >= '0' && p[k] <= '9') { num = num * 10 + (p[k] - '0'); any = 1; }
                    else if (any) break;
                }
                if (any) return num;
            }
        }
    }
    return -1;
}

static int tags_inited = 0;

void tags_init(void)
{
    if (!tags_inited) {
        mpg123_init();
        tags_inited = 1;
    }
}

void tags_exit(void)
{
    if (tags_inited) {
        mpg123_exit();
        tags_inited = 0;
    }
}

int tags_read(const char *path,
              char *title, size_t title_cap,
              char *artist, size_t artist_cap,
              char *album, size_t album_cap,
              int *number, int *seconds,
              unsigned char *cover, size_t cover_cap, size_t *cover_len,
              int want_cover)
{
    mpg123_handle *mh = NULL;
    int ret = -1;

    if (title) title[0] = '\0';
    if (artist) artist[0] = '\0';
    if (album) album[0] = '\0';
    if (number) *number = -1;
    if (seconds) *seconds = -1;
    if (cover_len) *cover_len = 0;

    if (!tags_inited) tags_init();
    int e = 0;
    mh = mpg123_new(NULL, &e);
    if (!mh) return -1;

    if (want_cover) {
        mpg123_param(mh, MPG123_ADD_FLAGS, MPG123_PICTURE, 0.0);
    }

    if (mpg123_open(mh, path) != MPG123_OK) goto out;

    /* lê um pouco p/ as tags do ID3v2 serem parseadas */
    {
        unsigned char buf[4096];
        size_t done;
        int reads = 0;
        while (reads < 4) {
            int rc = mpg123_read(mh, buf, sizeof(buf), &done);
            if (done) reads++;
            if (rc == MPG123_DONE) break;
            if (rc != MPG123_OK && rc != MPG123_NEW_FORMAT) break;
        }
        mpg123_seek(mh, 0, SEEK_SET);
    }

    mpg123_id3v1 *v1;
    mpg123_id3v2 *v2;
    if (mpg123_id3(mh, &v1, &v2) == MPG123_OK && v2) {
        copy_str(v2->title, title, title_cap);
        copy_str(v2->artist, artist, artist_cap);
        copy_str(v2->album, album, album_cap);
        int n = parse_track_no(v2, "TRCK");
        if (number && n >= 0) *number = n;
        if (want_cover && v2->picture && v2->pictures > 0) {
            for (size_t i = 0; i < v2->pictures; i++) {
                mpg123_picture *pic = &v2->picture[i];
                if (pic->type == mpg123_id3_pic_front_cover && pic->data && pic->size > 0) {
                    if (cover && cover_cap >= pic->size) {
                        memcpy(cover, pic->data, pic->size);
                        if (cover_len) *cover_len = pic->size;
                    } else if (cover_len) {
                        *cover_len = pic->size;
                    }
                    break;
                }
            }
        }
    }

    {
        long rate = 0;
        int chans = 0, enc = 0;
        long len = 0;
        if (mpg123_getformat(mh, &rate, &chans, &enc) == MPG123_OK && rate > 0) {
            len = mpg123_length(mh);
            if (seconds && len >= 0) *seconds = (int)(len / rate);
        }
    }

    ret = 0;
out:
    if (mh) { mpg123_close(mh); mpg123_delete(mh); }
    return ret;
}
