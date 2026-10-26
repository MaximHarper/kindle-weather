#!/usr/bin/env sh
# kindle-dash settings for the weather dashboard.

export WIFI_TEST_IP=${WIFI_TEST_IP:-1.1.1.1}

# Refresh at :20 and :50 from 06:20 to 23:50 (London time). The image is
# rendered on GitHub at roughly :07 and :37, so this leaves margin for delays.
# Overnight the Kindle sleeps and keeps the last forecast on screen.
export REFRESH_SCHEDULE=${REFRESH_SCHEDULE:-"20,50 6-23 * * *"}
export TIMEZONE=${TIMEZONE:-"Europe/London"}

# Full (flashing) refresh every 4th update to clear e-ink ghosting.
export FULL_DISPLAY_REFRESH_RATE=${FULL_DISPLAY_REFRESH_RATE:-4}

# Never swap the dashboard for the "sleeping" screen; keep the forecast visible.
export SLEEP_SCREEN_INTERVAL=86400

export LOW_BATTERY_REPORTING=${LOW_BATTERY_REPORTING:-false}
export LOW_BATTERY_THRESHOLD_PERCENT=10
