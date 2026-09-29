"use client";

import { FormEvent, useState } from "react";

const MAX_LENGTH = 6000;

type PublicReflection = {
  status: string;
  summary: string;
  understanding: string | null;
  boundary: string | null;
  responsibility: string | null;
  unresolved_percent: number | null;
  pending_question: { text: string } | null;
  next_step: string | null;
};

type ReflectionTurn = {
  thread_id: string;
  stage: string;
  public_view: PublicReflection;
  awaiting_input: boolean;
};

function ArrowIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20" width="20" height="20">
      <path d="M4 10h11M11 6l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.7" />
    </svg>
  );
}

export default function Home() {
  const [text, setText] = useState("");
  const [submittedText, setSubmittedText] = useState("");
  const [turn, setTurn] = useState<ReflectionTurn | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  async function submitReflection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = text.trim();
    if (!value || isLoading) return;
    setSubmittedText(value);
    setTurn(null);
    setError("");
    setIsLoading(true);
    try {
      const response = await fetch("/api/v1/dev/reflections", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: value }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Reflection request failed.");
      setTurn(body as ReflectionTurn);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Reflection request failed.");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main>
      <header className="site-header">
        <a className="brand" href="#top" aria-label="Causal home">
          <span className="brand-mark" aria-hidden="true">C</span>
          <span>Causal</span>
        </a>
        <div className="header-actions">
          <span className="status-dot"><i /> Live workflow test</span>
          <button className="text-button" type="button" disabled>Delete session</button>
        </div>
      </header>

      <section className="hero" id="top">
        <div className="eyebrow"><span>Guided reflection</span><span className="line" /></div>
        <h1>Follow a thought<br />toward its <em>conditions.</em></h1>
        <p className="hero-copy">
          Separate what happened, what you felt, and what you inferred. Explore possible
          causes while keeping uncertainty, accountability, and your boundaries visible.
        </p>
      </section>

      <section className="workspace" aria-labelledby="reflection-heading">
        <div className="workspace-main">
          <div className="section-number" aria-hidden="true">01</div>
          <div>
            <p className="kicker">Begin with your own words</p>
            <h2 id="reflection-heading">What is on your mind?</h2>
            <form onSubmit={submitReflection}>
              <label className="sr-only" htmlFor="reflection">Thought or feeling</label>
              <textarea
                id="reflection"
                value={text}
                maxLength={MAX_LENGTH}
                onChange={(event) => setText(event.target.value)}
                placeholder="Describe a thought, feeling, or situation you want to understand…"
              />
              <div className="composer-footer">
                <span>{text.length.toLocaleString()} / {MAX_LENGTH.toLocaleString()}</span>
                <button className="primary-button" type="submit" disabled={!text.trim() || isLoading}>
                  {isLoading ? "Examining…" : "Separate the strands"} {!isLoading && <ArrowIcon />}
                </button>
              </div>
            </form>
            <p className="privacy-note">
              <span aria-hidden="true">◇</span>
              Local workflow testing uses the configured model provider. Do not enter identifying details.
            </p>
          </div>
        </div>

        <aside className="workspace-aside" aria-label="How the reflection works">
          <p className="kicker">How it unfolds</p>
          <ol className="steps">
            <li><span>1</span><div><strong>Separate</strong><p>Identify reported events, feelings, interpretations, and missing context.</p></div></li>
            <li><span>2</span><div><strong>Explore</strong><p>Follow the most relevant thread with a small number of useful questions.</p></div></li>
            <li><span>3</span><div><strong>Understand</strong><p>Review tentative explanations alongside evidence, uncertainty, and boundaries.</p></div></li>
          </ol>
          <div className="principle-card">
            <span className="principle-symbol" aria-hidden="true">∿</span>
            <p>Understanding conditions can coexist with distance, accountability, and a clear boundary.</p>
          </div>
        </aside>
      </section>

      {submittedText && (
        <section className="captured" aria-live="polite">
          <div className="section-number" aria-hidden="true">02</div>
          <div className="captured-content">
            <p className="kicker">Captured for separation</p>
            <h2>Your words remain the source.</h2>
            <article className="statement-card">
              <span className="pill">{isLoading ? "Analyzing" : turn?.public_view.status || "Submitted"}</span>
              <blockquote>{submittedText}</blockquote>
              {error && <p role="alert">{error}</p>}
              {turn && (
                <div>
                  <p>{turn.public_view.summary}</p>
                  {turn.public_view.understanding && <p><strong>Understanding:</strong> {turn.public_view.understanding}</p>}
                  {turn.public_view.boundary && <p><strong>Boundary:</strong> {turn.public_view.boundary}</p>}
                  {turn.public_view.responsibility && <p><strong>Responsibility:</strong> {turn.public_view.responsibility}</p>}
                  {turn.public_view.pending_question && <p><strong>Question:</strong> {turn.public_view.pending_question.text}</p>}
                </div>
              )}
            </article>
          </div>
        </section>
      )}

      <section className="anatomy" aria-labelledby="anatomy-heading">
        <div>
          <p className="kicker">Output anatomy</p>
          <h2 id="anatomy-heading">An explanation keeps<br />its limits in view.</h2>
        </div>
        <div className="anatomy-grid">
          <article>
            <span className="mini-label reported">Reported</span>
            <h3>Your account</h3>
            <p>The original statement and later corrections stay visible as evidence about your experience.</p>
          </article>
          <article>
            <span className="mini-label tentative">Tentative</span>
            <h3>Possible conditions</h3>
            <p>Up to three explanations show supporting details, counterevidence, and unresolved weight.</p>
          </article>
          <article>
            <span className="mini-label boundary">Boundary</span>
            <h3>What you can preserve</h3>
            <p>Causal understanding leaves room for safety, consequences, responsibility, and distance.</p>
          </article>
        </div>
      </section>

      <footer>
        <span>Causal</span>
        <p>A reflection aid in development. It does not provide diagnosis or emergency support.</p>
      </footer>
    </main>
  );
}
