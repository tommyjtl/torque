# 0.1.0 headless board trial

2026-11-07: The UNO Q's Chromium 142 on Debian 13 loaded the localhost
server with cross-origin isolation and booted System 7.5.3 to the Finder.
`headless-finder.png` is a screenshot from that browser on the board. The 90
files on the board matched the release SHA-256 manifest. At one point the 11
processes associated with the isolated Chromium profile summed to 956 MiB
RSS; this double-counts shared pages and is not a measurement of unique RAM.
The board reported 2.51 GiB available at that moment. This is one headless
sample, not a benchmark or a guarantee for the regular graphical session.

The headless browser and server were stopped after testing; Torque remained
active. No physical-screen, touch, keyboard, audio, or GUI performance trial
was performed. No service or boot configuration was changed.
