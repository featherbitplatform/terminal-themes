# terminal-themes

Theme catalog for featherbit terminal. The app downloads `catalog.toml` from this repository
when you open the theme gallery and press Refresh, Install or Update; nothing else is fetched.

## Rules

- One file per theme: `themes/<id>.toml`. The id is a lowercase slug (for example
  `catppuccin-mocha`), equal to the file name, unique and fixed forever once published.
- Permissive licenses only. The theme's `[credit] license` must be one of: `MIT`,
  `Apache-2.0`, `BSD-2-Clause`, `BSD-3-Clause`, `ISC`, `Unlicense`, `CC0-1.0`, `Zlib`.
- Credits are required. Every `[credit]` field (project, author, url, license, copyright,
  license_file, description) must be present. `url` is `https://` and points to the theme's own
  main project. Copy the upstream license text into `LICENSES/` (plus its NOTICE text for
  Apache-2.0 sources) and point `license_file` at it.
- A theme file is a featherbit terminal color scheme (`name`, optional `font_family` and
  `font_size`, and a `[colors]` table of `#rrggbb` values) plus `id`, `version`, `variant`
  (`dark` or `light`) and the `[credit]` table.
- Raise `version` on every change to a theme. Ids never leave the catalog; a withdrawn theme
  is marked `withdrawn = true`, not removed.
- Merging to `main` publishes: `catalog.toml` on `main` is what the app downloads.
- Never name or compare to other terminal applications anywhere in this repository (files,
  descriptions, commit messages, pull requests). Credits link to the theme's own main project.

## Adding a theme

1. Add `themes/<id>.toml` and the license text under `LICENSES/`.
2. Run `python3 tools/catalog.py build` to regenerate `catalog.toml` and the table below.
3. Run the checks (Python 3.11 or newer, standard library only):

   ```
   python3 -m unittest discover -s tools
   python3 tools/catalog.py check
   python3 tools/catalog.py versions origin/main
   ```

   Low text contrast (foreground on background below 4.5:1) is reported as a warning, not an
   error.

## Themes

<!-- themes:start -->
| Theme | Variant | Project | Author | License |
|---|---|---|---|---|
| Catppuccin Mocha | dark | [Catppuccin](https://github.com/catppuccin/catppuccin) | Catppuccin | MIT |
<!-- themes:end -->

## License

The scripts and docs are Apache-2.0 (see `LICENSE`). Each theme's colors remain under the
upstream license stated in its file and in `LICENSES/`.
