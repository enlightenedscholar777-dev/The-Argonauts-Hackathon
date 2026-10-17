# Harbor-maester research website

A static research brief for the Harbor-maester harbor decision-support prototype. It explains the problem, architecture, mathematical methods, synthetic evaluation, operator interface and remaining field work. The interactive case selector illustrates recorded synthetic outcomes; the page does not connect to the Python engine.

The public site consists of `index.html`, `style.css`, `app.js`, `favicon.svg` and two product screenshots in `assets/`. There is no bundler, package install, runtime API key or external JavaScript dependency. All site assets use relative paths so the same files work at a GitHub Pages project URL.

## Preview and verify

Open `project-website/index.html` directly in a browser. If Python is available on your path, you can instead run a local server from the repository root:

```powershell
python -m http.server 3000 --directory project-website
```

Open `http://127.0.0.1:3000`. To check links and JavaScript:

```powershell
python project-website/check_site.py
node --check project-website/app.js
```

Python 3.11+ is sufficient for `check_site.py`. The published website needs no Python service.

## GitHub Pages deployment

The prepared [workflow](../.github/workflows/pages.yml) validates the site and uploads only public static assets. GitHub Pages serves `index.html` from the artifact root; it does not attempt to publish the repository's `project-website/` directory as a branch folder. The workflow triggers on website changes pushed to `v1-demo` or `main`, and can also be run manually after it is on the default branch.

1. In the GitHub repository, open **Settings → Pages** and choose **GitHub Actions** under **Build and deployment → Source**.
2. Commit the website and workflow on `v1-demo`, then push that branch. The **Harbor-maester website** workflow should validate and deploy it. If the `github-pages` environment restricts branches, allow `v1-demo` or publish after merging into the allowed branch.
3. Find the published URL in the workflow's deployment job or the repository Pages settings. For this repository the expected project-site form is `https://enlightenedscholar777-dev.github.io/The-Argonauts-Hackathon/`, subject to GitHub Pages configuration.

Nothing is pushed or published by the local website build. The workflow becomes active only after it reaches GitHub and the repository is configured for Pages. [GitHub's Pages Actions guide](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) describes the publishing source and permissions.

## Scientific and editorial boundary

- The 15-second warning lead, 13/20-second stale/lost transitions and 93-test result are sourced from the [capability audit](../docs/CAPABILITY_AUDIT.md) and [scenario results](../docs/harbor-evaluation.json).
- The 96.5% motion accuracy and 97% hypothesis coverage are measured only on held-out synthetic trajectories in the [motion evaluation](../docs/motion-evaluation.json). The [model card](../docs/MOTION_DETECTION.md) describes overlap between behavior classes and abstention.
- The diagrams and selected-case timeline are illustrations. The screenshots are captures of the running local app with synthetic data. The hero harbor drawing is not a navigation chart.
- New ports, real sensor integration, material recognition and operational impact remain future research. Avoid turning proposal language into shipped-capability claims.

See [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md) for content provenance, visual design and verification.
