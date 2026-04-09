const features = [
  {
    title: "Chat first",
    copy: "A calm assistant interface that feels natural, not like a dashboard. Ask normally. Zeph understands what you mean.",
  },
  {
    title: "Act on your Mac",
    copy: "Open apps, manage windows, type into documents, inspect the screen, and automate repeat work without leaving the conversation.",
  },
  {
    title: "Local by default",
    copy: "Your app, your files, your schedules, your memory. Zeph runs on your machine and keeps the operational context close.",
  },
  {
    title: "Updates built in",
    copy: "Zeph can check this site for the latest macOS release and install updates for packaged app builds.",
  },
];

const steps = [
  "Download the macOS app bundle.",
  "Open Zeph and sign in locally.",
  "Ask for anything from simple chat to full desktop actions.",
];

function App() {
  const macDownloadUrl = import.meta.env.VITE_MAC_DOWNLOAD_URL || "/downloads/Zeph.app.zip";
  const installNotesUrl = import.meta.env.VITE_INSTALL_NOTES_URL || "/downloads/INSTALL.txt";

  return (
    <div className="site-shell">
      <div className="ambient ambient-left" />
      <div className="ambient ambient-right" />

      <header className="topbar">
        <div className="brand">
          <span className="eyebrow">Desktop AI Agent</span>
          <strong>Zeph</strong>
        </div>
        <nav className="nav">
          <a href="#features">Features</a>
          <a href="#download">Download</a>
        </nav>
      </header>

      <main className="page">
        <section className="hero">
          <div className="hero-copy">
            <div className="pill-row">
              <span className="eyebrow">Local</span>
              <span className="eyebrow">Native macOS app</span>
              <span className="eyebrow">React interface</span>
            </div>
            <h1>
              take the pill
            </h1>
            <p className="lead">
              Zeph is the desktop AI agent that feels like a clean modern assistant, then actually opens windows,
              types into apps, reads your screen, and gets work done.
            </p>
            <div className="hero-actions">
              <a className="primary" href={macDownloadUrl}>
                Download for macOS
              </a>
              <a className="ghost" href="#download">
                See install notes
              </a>
            </div>
            <p className="microcopy">
              For Apple Silicon and Intel Macs running modern macOS, with in-app update checks for newer releases.
            </p>
          </div>

          <div className="hero-frame">
            <div className="window-shell">
              <div className="window-bar">
                <span />
                <span />
                <span />
              </div>
              <div className="window-body">
                <aside className="window-sidebar">
                  <div className="sidebar-chip">New chat</div>
                  <div className="sidebar-list">
                    <div className="sidebar-item active">Write a Google Doc</div>
                    <div className="sidebar-item">Show my windows</div>
                    <div className="sidebar-item">Sort Downloads</div>
                  </div>
                </aside>
                <section className="window-main">
                  <div className="status-line">
                    <span className="eyebrow">Ready</span>
                    <span className="eyebrow">claude-sonnet-4</span>
                  </div>
                  <div className="bubble agent">
                    Zeph can chat naturally, then act on your computer when you want it to.
                  </div>
                  <div className="bubble user">
                    Open a Google Doc and type a sentence about the moon.
                  </div>
                  <div className="bubble agent">
                    Working on that now.
                  </div>
                  <div className="composer-mock">
                    Message Zeph
                  </div>
                </section>
              </div>
            </div>
          </div>
        </section>

        <section className="section" id="features">
          <div className="section-head">
            <span className="eyebrow">What it does</span>
            <h2>The assistant look. The operator brain.</h2>
          </div>
          <div className="feature-grid">
            {features.map((feature) => (
              <article className="feature-card" key={feature.title}>
                <h3>{feature.title}</h3>
                <p>{feature.copy}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="section split-section">
          <div className="info-card">
            <span className="eyebrow">Why it feels different</span>
            <h2>Claude-style calm. Desktop-level power.</h2>
            <p>
              Zeph keeps the conversation clean and human, but under the surface it can launch apps, control the
              mouse and keyboard, work with files, use OCR, automate the browser, and schedule recurring tasks.
            </p>
          </div>
          <div className="info-card">
            <span className="eyebrow">Built for momentum</span>
            <h2>From one command to full workflows.</h2>
            <p>
              Use it as a fast chat companion or turn it loose on multi-step work like creating documents,
              organizing folders, or running recurring desktop routines.
            </p>
          </div>
        </section>

        <section className="section download-section" id="download">
          <div className="download-card">
            <div className="download-copy">
              <span className="eyebrow">Download Zeph</span>
              <h2>One app. One window. Full local control.</h2>
              <p>
                Download the current macOS build, drag it where you want it, and start using Zeph like a real app.
              </p>
              <div className="hero-actions">
                <a className="primary" href={macDownloadUrl}>
                  Download Zeph.app.zip
                </a>
                <a className="secondary" href={installNotesUrl}>
                  Install notes
                </a>
              </div>
            </div>
            <div className="steps-panel">
              <h3>How it works</h3>
              <ol>
                {steps.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

export default App;
