// serial_cmd.h — 115200 line-oriented command interface over UART0 (CH343).
//
// Commands (case-insensitive keyword, newline-terminated):
//   MODE idle|active|gate|sweep|idle-skip [k=<n>]  select controller mode
//   SET R=<n> THETA=<f>                      set refresh period / motion thresh
//   STATS                                    print one STATS {json} line
//   POWER on|off                             enable/disable INA219 sampling
//   HELP                                     list commands
//
// C2b boot-armed measurement (see meas.h and C2_mcu/PROMPT_C2b_usbmeter.md):
//   MEASURE <mode> <seconds> on-boot         arm a run across a power cycle
//                                            mode = idle-skip | gate | active |
//                                                   ctrl-k10 | ctrl-k5 | ctrl-k2
//   MEASURE off                              disarm
//   MEASURE status                           show arm state / stored-run count
//   DUMP                                     print all stored summaries as CSV
//   CLEAR                                    erase stored summaries
#pragma once

#ifdef __cplusplus
extern "C" {
#endif

// Launch the serial command task (reads stdin, mutates g_rt).
void cfs_serial_start(void);

// Format the current STATS as a single JSON line into `buf`. Also used at boot.
void cfs_serial_format_stats(char *buf, int buflen);

#ifdef __cplusplus
}
#endif
