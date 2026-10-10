/*
 * Universal WebKit GTK Script Injector for Buzz Desktop
 * =====================================================
 * Injects buzz_ui_enhancer.js into WebKit views without modifying the original binary.
 * Automatically resolves $HOME to locate buzz_ui_enhancer.js on any user account.
 */

#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef void* (*t_webkit_user_script_new)(const char* source, int injected_frames, int injection_time, const char* const* allow_list, const char* const* block_list);
typedef void (*t_webkit_user_content_manager_add_script)(void* manager, void* script);
typedef void (*t_real_register_handler)(void* manager, const char* name);
typedef void (*t_real_set_dev_extras)(void* settings, int enabled);

/* Enable developer extras / inspect element */
void webkit_settings_set_enable_developer_extras(void* settings, int enabled) {
    t_real_set_dev_extras real_fn = (t_real_set_dev_extras)dlsym(RTLD_NEXT, "webkit_settings_set_enable_developer_extras");
    if (real_fn) {
        real_fn(settings, 1);
    }
}

/* Intercept script message handler registration to inject our custom JS bundle */
void webkit_user_content_manager_register_script_message_handler(void* manager, const char* name) {
    static t_real_register_handler real_fn = NULL;
    static t_webkit_user_script_new p_script_new = NULL;
    static t_webkit_user_content_manager_add_script p_add_script = NULL;

    if (!real_fn) {
        real_fn = (t_real_register_handler)dlsym(RTLD_NEXT, "webkit_user_content_manager_register_script_message_handler");
        p_script_new = (t_webkit_user_script_new)dlsym(RTLD_DEFAULT, "webkit_user_script_new");
        p_add_script = (t_webkit_user_content_manager_add_script)dlsym(RTLD_DEFAULT, "webkit_user_content_manager_add_script");
    }

    if (p_script_new && p_add_script && manager) {
        char js_path[1024];
        const char* home = getenv("HOME");
        if (home && strlen(home) > 0) {
            snprintf(js_path, sizeof(js_path), "%s/.local/share/xyz.block.buzz.app/buzz_ui_enhancer.js", home);
        } else {
            strncpy(js_path, "/home/ncthang/.local/share/xyz.block.buzz.app/buzz_ui_enhancer.js", sizeof(js_path) - 1);
        }

        FILE* f = fopen(js_path, "r");
        if (f) {
            fseek(f, 0, SEEK_END);
            long sz = ftell(f);
            fseek(f, 0, SEEK_SET);
            char* buf = (char*)malloc(sz + 1);
            if (buf) {
                size_t read_bytes = fread(buf, 1, sz, f);
                buf[read_bytes] = '\0';
                /* WEBKIT_USER_CONTENT_INJECT_ALL_FRAMES = 0, WEBKIT_USER_SCRIPT_INJECT_AT_DOCUMENT_START = 0 */
                void* script = p_script_new(buf, 1, 0, NULL, NULL);
                if (script) {
                    p_add_script(manager, script);
                    fprintf(stderr, "[BUZZ ENHANCER] Injected %zu bytes from %s\n", read_bytes, js_path);
                }
                free(buf);
            }
            fclose(f);
        } else {
            fprintf(stderr, "[BUZZ ENHANCER] Notice: Could not open %s\n", js_path);
        }
    }

    if (real_fn) {
        real_fn(manager, name);
    }
}
