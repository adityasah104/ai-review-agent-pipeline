import { themes as prismThemes } from 'prism-react-renderer';
import type { Config } from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'AI PR Review & Auto-Fix Agent',
  tagline: 'Autonomous PR review and auto-fix for Azure DevOps',
  favicon: 'img/logo.svg',

  url: 'https://adityasah104.github.io',
  baseUrl: '/ai-review-agent-pipeline/',

  organizationName: 'adityasah104',   // GitHub org/user
  projectName: 'ai-review-agent-pipeline',       // Repo name
  deploymentBranch: 'gh-pages',

  onBrokenLinks: 'throw',
  onBrokenMarkdownLinks: 'warn',

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          // editUrl: 'https://gitlab.com/adityasah104/ai-review-agent-pipeline/-/edit/main/Docs/my-project-docs/',
        },
        blog: false, // disable blog if you don't need it
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    // image: 'img/social-card.png',
    navbar: {
      title: 'AI PR Review Agent',
      logo: {
        alt: 'Project Logo',
        src: 'img/logo.svg',
      },
      items: [
        { to: '/docs/getting-started', label: 'Getting Started', position: 'left' },
        { to: '/docs/architecture', label: 'Architecture', position: 'left' },
        { to: '/docs/configuration', label: 'Configuration', position: 'left' },
        { to: '/docs/azure-devops', label: 'Azure DevOps Setup', position: 'left' },
        { to: '/docs/safety', label: 'Safety', position: 'left' },
        { to: '/docs/limitations', label: 'Limitations', position: 'left' },
        { to: '/roadmap', label: 'Roadmap', position: 'left' },
        {
          href: 'https://gitlab.com/adityasah104/ai-review-agent-pipeline',
          label: 'GitLab',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Docs',
          items: [
            { label: 'Getting Started', to: '/docs/getting-started' },
            { label: 'Configuration', to: '/docs/configuration' },
            { label: 'Problems & Solutions', to: '/docs/problems-faced' },
          ],
        },
        {
          title: 'Community',
          items: [
            { label: 'GitLab Issues', href: 'https://gitlab.com/adityasah104/ai-review-agent-pipeline/-/issues' },
            { label: 'Discussions', href: 'https://gitlab.com/adityasah104/ai-review-agent-pipeline/-/merge_requests' },
          ],
        },
        {
          title: 'More',
          items: [
            { label: 'Roadmap', to: '/roadmap' },
            { label: 'GitLab', href: 'https://gitlab.com/adityasah104/ai-review-agent-pipeline' },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} AI PR Review Agent. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;