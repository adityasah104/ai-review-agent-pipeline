import React from 'react';
import ComponentCreator from '@docusaurus/ComponentCreator';

export default [
  {
    path: '/ai-review-agent-pipeline/roadmap',
    component: ComponentCreator('/ai-review-agent-pipeline/roadmap', 'd86'),
    exact: true
  },
  {
    path: '/ai-review-agent-pipeline/docs',
    component: ComponentCreator('/ai-review-agent-pipeline/docs', '0b1'),
    routes: [
      {
        path: '/ai-review-agent-pipeline/docs',
        component: ComponentCreator('/ai-review-agent-pipeline/docs', 'fe2'),
        routes: [
          {
            path: '/ai-review-agent-pipeline/docs',
            component: ComponentCreator('/ai-review-agent-pipeline/docs', '8a3'),
            routes: [
              {
                path: '/ai-review-agent-pipeline/docs/architecture',
                component: ComponentCreator('/ai-review-agent-pipeline/docs/architecture', 'bbf'),
                exact: true,
                sidebar: "tutorialSidebar"
              },
              {
                path: '/ai-review-agent-pipeline/docs/azure-devops',
                component: ComponentCreator('/ai-review-agent-pipeline/docs/azure-devops', '710'),
                exact: true,
                sidebar: "tutorialSidebar"
              },
              {
                path: '/ai-review-agent-pipeline/docs/configuration',
                component: ComponentCreator('/ai-review-agent-pipeline/docs/configuration', '7b0'),
                exact: true,
                sidebar: "tutorialSidebar"
              },
              {
                path: '/ai-review-agent-pipeline/docs/customization',
                component: ComponentCreator('/ai-review-agent-pipeline/docs/customization', 'b8c'),
                exact: true,
                sidebar: "tutorialSidebar"
              },
              {
                path: '/ai-review-agent-pipeline/docs/getting-started',
                component: ComponentCreator('/ai-review-agent-pipeline/docs/getting-started', '1cd'),
                exact: true,
                sidebar: "tutorialSidebar"
              },
              {
                path: '/ai-review-agent-pipeline/docs/limitations',
                component: ComponentCreator('/ai-review-agent-pipeline/docs/limitations', '87b'),
                exact: true,
                sidebar: "tutorialSidebar"
              },
              {
                path: '/ai-review-agent-pipeline/docs/problems-faced',
                component: ComponentCreator('/ai-review-agent-pipeline/docs/problems-faced', '2a5'),
                exact: true,
                sidebar: "tutorialSidebar"
              },
              {
                path: '/ai-review-agent-pipeline/docs/safety',
                component: ComponentCreator('/ai-review-agent-pipeline/docs/safety', '49b'),
                exact: true,
                sidebar: "tutorialSidebar"
              },
              {
                path: '/ai-review-agent-pipeline/docs/troubleshooting',
                component: ComponentCreator('/ai-review-agent-pipeline/docs/troubleshooting', 'a70'),
                exact: true,
                sidebar: "tutorialSidebar"
              }
            ]
          }
        ]
      }
    ]
  },
  {
    path: '/ai-review-agent-pipeline/',
    component: ComponentCreator('/ai-review-agent-pipeline/', 'bad'),
    exact: true
  },
  {
    path: '*',
    component: ComponentCreator('*'),
  },
];
