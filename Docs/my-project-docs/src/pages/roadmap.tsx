import type { ReactNode } from 'react';
import Layout from '@theme/Layout';

const ITEMS = [
  {
    title: 'Model Upgrade',
    body: 'Move to a model with stronger diff-generation reliability, enabling diff-fenced edits and removing truncation risk.',
  },
  {
    title: 'Unit Test Integration',
    body: 'Run the project test suite inside the CI-fix loop to catch business-logic regressions before the fix PR opens.',
  },
  {
    title: 'Stricter Pre-Commit Hooks',
    body: 'Run import-sorting natively before the AI pass to reduce wasted tokens on avoidable issues.',
  },
];

export default function Roadmap(): ReactNode {
  return (
    <Layout title="Roadmap" description="Planned improvements">
      <main className="container margin-vert--xl">
        <h1>Roadmap</h1>
        {ITEMS.map((item) => (
          <div key={item.title} style={{ marginBottom: '2rem' }}>
            <h3>{item.title}</h3>
            <p>{item.body}</p>
          </div>
        ))}
      </main>
    </Layout>
  );
}