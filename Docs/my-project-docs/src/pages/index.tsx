import type { ReactNode } from 'react';
import Layout from '@theme/Layout';
import Link from '@docusaurus/Link';
import styles from './index.module.css';

const FEATURES = [
  {
    title: 'Multi-Angle Automated Review',
    desc: 'Three specialized LLM passes run in parallel, followed by Codium PR-Agent for intelligent deduplication and refinement.',
  },
  {
    title: 'True Auto-Fix, Not Just Comments',
    desc: 'Checks out the code, applies fixes with Aider, and pushes a working branch.',
  },
  {
    title: 'Self-Healing CI Loop',
    desc: 'Runs native linters after every fix, feeds errors back to the model, and retries — bounded and guaranteed to terminate.',
  },
  {
    title: 'Branch-Safe by Design',
    desc: 'Fixes land on an isolated agent/<branch>, never the developer\'s own branch.',
  },
  {
    title: 'Infinite-Loop Protection',
    desc: 'Detects and skips runs triggered by the agent\'s own commits. Fails closed on ambiguity.',
  },
  {
    title: 'Confidence-Gated Auto-Fixing',
    desc: 'Only fixes above your configured threshold are applied automatically.',
  },
];

const PIPELINE_STAGES = ['PR Opened', 'Review', 'Auto-Fix', 'Lint Loop', 'Merge-Ready PR'];

function PipelineHero() {
  return (
    <div className={styles.pipelineHero}>
      {PIPELINE_STAGES.map((stage, i) => (
        <div className={styles.pipelineStageWrap} key={stage}>
          <div
            className={styles.pipelineStage}
            style={{ animationDelay: `${i * 0.4}s` }}
          >
            {stage}
          </div>
          {i < PIPELINE_STAGES.length - 1 && (
            <div className={styles.pipelineArrow} style={{ animationDelay: `${i * 0.4 + 0.2}s` }}>
              →
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function HomepageHeader() {
  return (
    <header className={styles.heroBanner}>
      <div className="container">
        <h1 className={styles.heroTitle}>AI PR Review & Auto-Fix Agent</h1>
        <p className={styles.heroSubtitle}>
          An autonomous pipeline that reviews, fixes, and re-validates every pull request —
          before a human ever looks at it.
        </p>
        <PipelineHero />
        <div className={styles.heroButtons}>
          <Link className={styles.primaryButton} to="/docs/getting-started">
            Get Started
          </Link>
          <Link className={styles.secondaryButton} href="https://github.com/adityasah104/ai-review-agent-pipeline">
            View on GitHub
          </Link>
        </div>
      </div>
    </header>
  );
}

function FeatureGrid() {
  return (
    <section className={styles.featuresSection}>
      <div className="container">
        <div className={styles.featureGrid}>
          {FEATURES.map((f) => (
            <div className={styles.featureCard} key={f.title}>
              <h3>{f.title}</h3>
              <p>{f.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export default function Home(): ReactNode {
  return (
    <Layout
      title="AI PR Review & Auto-Fix Agent"
      description="Autonomous PR review and auto-fix pipeline for Azure DevOps"
    >
      <HomepageHeader />
      <main>
        <FeatureGrid />
      </main>
    </Layout>
  );
}