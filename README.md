# Fink Geospatial

Portfolio and sandbox site for Fink Geospatial: personal GIS projects. Published with GitHub Pages at <https://finkgeo.com>.

Plain HTML and CSS, no build step. Edit a file, commit, push, and Pages redeploys.

## Layout

| Path | What it is |
| --- | --- |
| `index.html` | Home page, with the About, Projects, and Contact sections |
| `tucson-golf-water/index.html` | Placeholder page for the Tucson golf course water map |
| `404.html` | Not-found page |
| `assets/style.css` | Shared styles (late-90s desktop look; plain CSS, no external requests) |
| `assets/*.svg` | Pixel-style icons. `globe.svg` doubles as the favicon. |
| `CNAME` | Tells GitHub Pages the custom domain (`finkgeo.com`). Don't delete it. |
| `.nojekyll` | Tells Pages to serve the files as-is, skipping Jekyll |

## TODO

- Replace the About placeholder text in `index.html` (search for `TODO`).
- Embed the real map in `tucson-golf-water/index.html`.
- Bump the "Last updated" date in each page footer when content changes.

## Preview locally

From this folder, run any static file server, for example:

```
python -m http.server 8000
```

then open <http://localhost:8000>. Links use root-relative paths (`/assets/...`),
so opening the HTML files directly from disk will not load the styles.
