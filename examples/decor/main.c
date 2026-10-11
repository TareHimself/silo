#include <stdio.h>

#include <libdecor.h>
#include <wayland-client.h>

static void on_error(struct libdecor *context, enum libdecor_error error, const char *message) {
    (void)context;
    fprintf(stderr, "libdecor error %d: %s\n", error, message);
}

static struct libdecor_interface interface = {.error = on_error};

int main(void) {
    struct wl_display *display = wl_display_connect(NULL);
    if (!display) {
        printf("no Wayland display to connect to\n");
        return 2;
    }
    struct libdecor *context = libdecor_new(display, &interface);
    printf("libdecor context: %s\n", context ? "created" : "failed");
    if (context) {
        libdecor_unref(context);
    }
    wl_display_disconnect(display);
    return context ? 0 : 1;
}
