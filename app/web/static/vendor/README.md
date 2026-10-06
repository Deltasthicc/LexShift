# Vendored front-end files

Copied unmodified from the official npm packages so the interface runs fully offline (nothing is fetched at run time). Downloaded on
2026-10-06 with `npm pack`, at the project owner's request. `ScrollToPlugin` and `Flip` were copied on 2026-10-07 from the same, already downloaded and
hash-checked `gsap-3.15.0.tgz`: nothing new was fetched. The Geist font was downloaded on 2026-10-07 the same way (`npm pack`), after the
project owner approved it.

| File here | Package and version | Licence | Size | SHA-256 of the file |
|---|---|---|---|---|
| `gsap/gsap.min.js` | `gsap` 3.15.0, `dist/gsap.min.js` | GSAP Standard "no charge" licence (https://gsap.com/standard-license), stated in the file header | 72,927 bytes | `92bb9a96476f983d212a2bc4f54c889039c1696dd4461d40a736860938570fbb` |
| `gsap/ScrollTrigger.min.js` | `gsap` 3.15.0, `dist/ScrollTrigger.min.js` | same | 44,575 bytes | `b0b14d67b55b0c43c756ac0b106cfcb09d0879945f6ead64451065b0672916a2` |
| `gsap/ScrollToPlugin.min.js` | `gsap` 3.15.0, `dist/ScrollToPlugin.min.js` (eased scrolling to anchors) | same | 4,059 bytes | `07cfd328e41012ae60b5614c2e58399fc13af8b1aec765febe770d4eb3e62fcd` |
| `gsap/Flip.min.js` | `gsap` 3.15.0, `dist/Flip.min.js` (animated re-ordering of results) | same | 25,534 bytes | `cbe3ca726350f8d230da38a14ce2384e7772e05a45cee6144dd7fe6dde868c2f` |
| `../fonts/outfit-latin-wght-normal.woff2` | `@fontsource-variable/outfit` 5.3.0 (Outfit variable font, Latin) | SIL Open Font License 1.1 (`../fonts/OFL.txt`) | 32,292 bytes | `6c18d579fd87c3776be068b762cbc83fde3acb543d49eabd3ade842eb987e887` |
| `../fonts/outfit-latin-ext-wght-normal.woff2` | same package (Latin Extended) | same | 14,808 bytes | `0f53d1c03b3918d744a843b5039001ee31695ca1e255e3914188df81beb461e9` |
| `../fonts/geist-latin-wght-normal.woff2` | `@fontsource-variable/geist` 5.3.0 (Geist variable font, Latin; the interface's first-choice font) | SIL Open Font License 1.1 (`../fonts/OFL-Geist.txt`) | 29,400 bytes | `19f9c92546aa300c312235e3125af1b81394d8db9a4bc4a425cd5b641d2d54e1` |
| `../fonts/geist-latin-ext-wght-normal.woff2` | same package (Latin Extended) | same | 16,512 bytes | `824f485b5d26e2f2da3c2b236132ece1bc8e4e43373452950bb0e40548b4313f` |

SHA-256 of the downloaded tarballs: `gsap-3.15.0.tgz` `d2e33ad202d4811e9084883f7ff9a27967ac4095caef51ca4c9d20697a253b1c`;
`fontsource-variable-outfit-5.3.0.tgz` `06ab798b993eda0cfe3c8adf31030be5da4ccaaca3e226d93ab291c4a96e5957`; `fontsource-variable-geist-5.3.0.tgz`
`533dd66117795ac12316fb05fce27736c4bc63c31613b302d0a5285ca3a291d7`. Geist Mono was not downloaded: code and ids use the system monospace font.
Outfit stays bundled as the fallback if Geist fails to load.

Checks made before adding them: the GSAP files contain no `fetch`, `XMLHttpRequest` or `importScripts`, and the only URLs in them are
the licence reference and XML namespace identifiers. Neither library touches the network.

To update: run `npm pack gsap@<version> @fontsource-variable/outfit@<version> @fontsource-variable/geist@<version>`, copy the same eight files, update the table above, and re-run
`python -m pytest tests/test_app_server.py`. The page's Content-Security-Policy (`app/server.py`) allows scripts and fonts from its own
origin only, so a file that is not in this folder will not load.
