# Kindle weather dashboard

A weather dashboard for a jailbroken Kindle 4, shown landscape (Kindle turned 90° anticlockwise, buttons on the right).

- Next 24 hours: chance of rain as bars, temperature as a line, conditions along the top
- Current temperature, today's high/low, and a one-line rain summary
- Data from [Open-Meteo](https://open-meteo.com/) (free, no API key)

![preview](https://raw.githubusercontent.com/MaximHarper/kindle-weather/dashboard/preview.png)

## How it works

A GitHub Action runs `render.py` every half hour and force-pushes the result to the `dashboard` branch:

- `dashboard.png` – 600×800, 16 greys, pre-rotated for the Kindle's framebuffer
- `preview.png` – the same image upright, for checking

The Kindle runs [kindle-dash](https://github.com/pascalw/kindle-dash), which wakes on a schedule, downloads `dashboard.png` and goes back to sleep:

```
https://raw.githubusercontent.com/MaximHarper/kindle-weather/dashboard/dashboard.png
```

Use **Actions → Render dashboard → Run workflow** for an immediate refresh.

## Running locally

```sh
pip install pillow
python3 render.py --preview upright.png                    # live data
python3 render.py --sample --preview upright.png           # offline sample data
python3 render.py --lat 45.46 --lon 9.19 --place Milan     # another city
python3 render.py --orientation portrait                   # Kindle upright
```

Fonts: [Inter](https://github.com/rsms/inter), SIL Open Font License 1.1 (see `fonts/OFL.txt`).
