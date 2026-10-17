# Website implementation report

## Scope

The early static site described an older “Harbor Watch” prototype and contained obsolete numerical claims. This revision replaces the page with the current Harbor-maester name, architecture, synthetic cases, motion-model work, operator screenshots, research agenda and references. The website remains a static, independent artifact suitable for a GitHub Pages project site.

## Content provenance

| Website content | Repository source |
| --- | --- |
| Research question, capability boundary, synthetic warning lead, outage and tests | `docs/CAPABILITY_AUDIT.md`, `docs/harbor-evaluation.json` |
| Constant-velocity filter, innovation gate and Joseph covariance | `src/harbor_engine/tracking.py` |
| Mean trajectory, uncertainty and 32 sampled paths | `src/harbor_engine/forecast.py` |
| Mission permissions, freshness, action selection | `src/harbor_engine/policy.py` |
| Surface closest approach, route deviation and delay | `src/harbor_engine/surface.py` |
| Motion features, forest artifact, test split and abstention | `src/harbor_engine/motion.py`, `scripts/train_motion.py`, `docs/MOTION_DETECTION.md`, `docs/motion-evaluation.json` |
| Commit-before-publication, API and optional AI boundary | `src/harbor_engine/coordinator.py`, `src/harbor_engine/api.py`, `src/harbor_engine/ai/worker.py` |
| Product interface | `harbor_simulation/app.py`, local synthetic demo screenshots copied into `assets/` |

The external references on the site are the original [Time Series Forest paper](https://arxiv.org/abs/1302.2277) and [TrashCan dataset paper](https://arxiv.org/abs/2007.08097). They provide research context; this project does not claim to implement either paper's model. The motion model is its own small random forest trained on synthetic trajectory features.

## Presentation

The new layout adopts an editorial research-brief style: a chart-like harbor figure, abstract with marginalia and keywords, formal methods, system invariants, interactive case timelines, measured results, limitations and citations. The four equations correspond to implemented calculations or concise notation for them. The drawing is explicitly illustrative, while the two screenshots show the actual operator UI.

No external images, remote scripts, CSS framework, chart library or analytics are required. Native HTML, CSS and a small JavaScript file handle navigation and the case selector. The case selector uses recorded text from the evaluation; it neither fabricates live engine output nor sends any request. Page content remains readable if JavaScript is unavailable; the first case is in the HTML.

## Deployment and checks

The Pages workflow stages only `index.html`, CSS, JavaScript, icon and two PNGs at the artifact root. It runs the standard-library link checker and `node --check` before uploading. The CSS supports desktop, tablet, phone, print and reduced-motion preferences. Anchor navigation and interactive controls use native links/buttons; the mobile navigation exposes its expanded state.

Static evaluation values are content snapshots, so refresh them alongside their cited local JSON and documentation if the simulator or model evaluation changes. They are explicitly labeled synthetic to prevent interpreting them as real-world incident or safety metrics.
