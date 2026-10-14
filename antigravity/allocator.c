#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/sysinfo.h>
#include <sys/stat.h>
#include <unistd.h>
#include <time.h>
#include <stdarg.h>

#define CGROUP_PATH "/sys/fs/cgroup/nexus"
#define LOG_FILE    "/tmp/nexus-allocator.log"
#define FOUR_GB     4294967296L

static void log_msg(const char *level, const char *fmt, ...) {
    char time_buf[64];
    time_t now = time(NULL);
    struct tm *tm_info = localtime(&now);
    strftime(time_buf, sizeof(time_buf), "%Y-%m-%d %H:%M:%S", tm_info);

    char msg[1024];
    va_list args;
    va_start(args, fmt);
    vsnprintf(msg, sizeof(msg), fmt, args);
    va_end(args);

    /* Print to console */
    printf("[%s] [%-7s] [allocator] %s\n", time_buf, level, msg);
    fflush(stdout);

    /* Append to log file */
    FILE *lf = fopen(LOG_FILE, "a");
    if (lf) {
        fprintf(lf, "[%s] [%-7s] [allocator:%d] %s\n", time_buf, level, getpid(), msg);
        fclose(lf);
    }
}

static int write_file(const char *path, const char *content) {
    FILE *f = fopen(path, "w");
    if (!f) {
        log_msg("ERROR", "Failed to write %s: %s (errno: %d)", path, strerror(errno), errno);
        return -1;
    }
    fputs(content, f);
    fclose(f);
    log_msg("DEBUG", "Wrote '%s' to %s", content, path);
    return 0;
}

int main(int argc, char *argv[]) {
    int target_pct = 70;
    if (argc > 1) {
        int parsed = atoi(argv[1]);
        if (parsed >= 10 && parsed <= 95) {
            target_pct = parsed;
        } else {
            log_msg("WARNING", "Invalid percentage '%s' provided (must be 10-95). Defaulting to 70%%.", argv[1]);
        }
    }

    log_msg("INFO", "Starting Nexus Cgroup Allocator (PID: %d, UID: %d, GID: %d, Target: %d%%)",
            getpid(), getuid(), getgid(), target_pct);

    struct sysinfo info;
    if (sysinfo(&info) != 0) {
        log_msg("CRITICAL", "sysinfo() failed: %s (errno: %d)", strerror(errno), errno);
        return 1;
    }

    long total = (long)info.totalram * info.mem_unit;
    long free_ram = (long)info.freeram * info.mem_unit;
    log_msg("INFO", "Host System Memory: Total = %ld MB, Free = %ld MB", total / (1024 * 1024), free_ram / (1024 * 1024));

    long limit_pct = (long)(total * (target_pct / 100.0));
    long limit_res = total - FOUR_GB;
    long limit     = (limit_pct < limit_res) ? limit_pct : limit_res;
    if (limit <= 0) {
        limit = total / 3;
    }

    log_msg("INFO", "Calculated limits: %d%% = %ld MB, Floor reserved = %ld MB, Selected max = %ld MB (%.1f GB)",
            target_pct, limit_pct / (1024 * 1024), limit_res / (1024 * 1024), limit / (1024 * 1024), limit / 1073741824.0);

    if (mkdir(CGROUP_PATH, 0755) != 0 && errno != EEXIST) {
        log_msg("WARNING", "mkdir(%s) failed: %s (errno: %d)", CGROUP_PATH, strerror(errno), errno);
    } else {
        log_msg("INFO", "Cgroup directory ready: %s", CGROUP_PATH);
    }

    /* Assign ownership to user dheeraj (UID 1000, GID 1000) */
    chown(CGROUP_PATH, 1000, 1000);
    chown(CGROUP_PATH "/cgroup.procs", 1000, 1000);
    chown(CGROUP_PATH "/cgroup.threads", 1000, 1000);
    chmod(CGROUP_PATH "/cgroup.procs", 0666);

    char buf[64];
    snprintf(buf, sizeof(buf), "%ld", limit);
    if (write_file(CGROUP_PATH "/memory.max", buf) != 0) {
        log_msg("ERROR", "Failed to set memory.max on %s", CGROUP_PATH);
        return 1;
    }

    long high = (long)(limit * 0.9);
    snprintf(buf, sizeof(buf), "%ld", high);
    write_file(CGROUP_PATH "/memory.high", buf);

    chown(CGROUP_PATH "/memory.max", 1000, 1000);
    chown(CGROUP_PATH "/memory.high", 1000, 1000);
    chmod(CGROUP_PATH "/memory.max", 0666);
    chmod(CGROUP_PATH "/memory.high", 0666);
    log_msg("DEBUG", "Configured user ownership (1000:1000) on cgroup memory limits");

    log_msg("INFO", "Nexus cgroup initialized successfully!");
    log_msg("INFO", "  Target path : %s", CGROUP_PATH);
    log_msg("INFO", "  memory.max  = %ld bytes (%.1f GB)", limit, limit / 1073741824.0);
    log_msg("INFO", "  memory.high = %ld bytes (%.1f GB)", high,  high  / 1073741824.0);
    return 0;
}
