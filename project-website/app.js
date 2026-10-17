(() => {
  const menu = document.querySelector('.menu-toggle');
  const links = document.querySelector('#nav-links');
  if (menu && links) {
    const closeMenu = () => {
      links.classList.remove('is-open');
      menu.setAttribute('aria-expanded', 'false');
      menu.setAttribute('aria-label', 'Open navigation');
    };
    menu.addEventListener('click', () => {
      const open = links.classList.toggle('is-open');
      menu.setAttribute('aria-expanded', String(open));
      menu.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
    });
    links.addEventListener('click', (event) => {
      if (event.target.closest('a')) closeMenu();
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && links.classList.contains('is-open')) {
        closeMenu();
        menu.focus();
      }
    });
  }

  const cases = {
    approach: {
      type: 'FORECAST / ZONE POLICY',
      title: 'An unverified contact approaches a restricted zone.',
      number: '15 s', numberLabel: 'synthetic warning lead',
      description: 'High concern appeared at scenario second 36. The estimated mean path reached the demo zone at second 51; the operator was shown a human-review recommendation before that modeled entry.',
      observation: 'Noisy range and bearing reports establish a moving track.',
      inference: 'A fresh forecast intersects a restricted polygon.',
      action: 'Request a human review and verify operating permission.',
      first: '36 s', second: '51 s', firstLabel: 'First high concern', secondLabel: 'Estimated zone entry',
      a: '40%', b: '70%', fill: '70%',
      caption: 'Source: repeatable in-process synthetic evaluation. These seconds are scenario time, not measured responder time.'
    },
    outage: {
      type: 'FRESHNESS / GRACEFUL DEGRADATION',
      title: 'A sonar source stops reporting.',
      number: '13 / 20 s', numberLabel: 'stale / lost states',
      description: 'The source stops at scenario second 10; its last accepted position is from second 9. The assessment marks position evidence stale at second 13 and lost at second 20.',
      observation: 'No new sonar position arrives, although the clock and other streams continue.',
      inference: 'Observation age crosses the freshness and lost-data thresholds.',
      action: 'Request a fresh observation and avoid relying on the old trajectory.',
      first: '13 s', second: '20 s', firstLabel: 'Position stale', secondLabel: 'Position lost',
      a: '38%', b: '76%', fill: '76%',
      caption: 'Source: synthetic sensor-outage test. No automatic vessel control or dispatch occurs.'
    },
    motion: {
      type: 'TEMPORAL FEATURES / ADVISORY ML',
      title: 'A small track moves with the harbor current.',
      number: '30 s', numberLabel: 'minimum motion history',
      description: 'Thirty-two synthetic objects can be observed across eight Long Beach areas. A local model waits for at least 16 observations over 30 seconds before proposing a behavior class.',
      observation: 'Positions and measurement uncertainty arrive every two scenario seconds.',
      inference: 'Speed variation, turns and path straightness may fit a drift-like pattern.',
      action: 'Inspect camera or imaging sonar evidence; material remains unknown.',
      first: '0 s', second: '30 s', firstLabel: 'First observation', secondLabel: 'Earliest hypothesis',
      a: '9%', b: '76%', fill: '76%',
      caption: 'Source: synthetic object stream and local random forest. Motion does not identify plastic, fish or people.'
    }
  };

  const fields = {
    type: 'case-type', title: 'case-title', number: 'case-number', numberLabel: 'case-number-label',
    description: 'case-description', observation: 'case-observation', inference: 'case-inference',
    action: 'case-action', first: 'marker-a-time', second: 'marker-b-time',
    firstLabel: 'timeline-start', secondLabel: 'timeline-end', caption: 'case-caption'
  };
  const caseButtons = [...document.querySelectorAll('[data-case]')];
  caseButtons.forEach((button) => {
    button.addEventListener('click', () => {
      const data = cases[button.dataset.case];
      if (!data) return;
      for (const [key, id] of Object.entries(fields)) {
        document.getElementById(id).textContent = data[key];
      }
      document.getElementById('marker-a').style.left = data.a;
      document.getElementById('marker-b').style.left = data.b;
      document.getElementById('timeline-fill').style.width = data.fill;
      caseButtons.forEach((item) => {
        const selected = item === button;
        item.classList.toggle('is-active', selected);
        item.setAttribute('aria-pressed', String(selected));
      });
    });
  });

  const navAnchors = [...document.querySelectorAll('.nav-links a[href^="#"]')];
  const observedSections = navAnchors.map((anchor) => ({
    anchor, section: document.querySelector(anchor.getAttribute('href'))
  })).filter((item) => item.section);
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        navAnchors.forEach((anchor) => anchor.classList.remove('is-active'));
        const current = observedSections.find((item) => item.section === entry.target);
        if (current) current.anchor.classList.add('is-active');
      }
    }, { rootMargin: '-90px 0px -62% 0px', threshold: 0 });
    observedSections.forEach((item) => observer.observe(item.section));
  }
})();
