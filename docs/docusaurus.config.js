// @ts-check
/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'Anchor',
  tagline: 'Make lesser models behave like Mythos',
  favicon: 'img/favicon.ico',
  url: 'https://carefreeinv.com',
  baseUrl: '/anchor/',
  organizationName: 'carefreeinv',
  projectName: 'anchor',
  trailingSlash: false,
  onBrokenLinks: 'warn',
  markdown: {
    mermaid: true,
    hooks: { onBrokenMarkdownLinks: 'warn' },
  },
  themes: ['@docusaurus/theme-mermaid'],
  i18n: { defaultLocale: 'en', locales: ['en'] },
  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          routeBasePath: '/',
          sidebarPath: './sidebars.js',
          editUrl: 'https://github.com/carefreeinv/anchor/edit/main/docs/',
        },
        blog: {
          showReadingTime: true,
          blogSidebarTitle: 'Posts',
          onUntruncatedBlogPosts: 'warn',
          editUrl: 'https://github.com/carefreeinv/anchor/edit/main/docs/',
        },
        theme: { customCss: './src/css/custom.css' },
      }),
    ],
  ],
  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      // Default og:image / twitter:image for social shares (1200×630)
      image: 'img/og-card.png',
      metadata: [
        {
          name: 'twitter:card',
          content: 'summary_large_image',
        },
      ],
      navbar: {
        title: 'Anchor',
        items: [
          { type: 'docSidebar', sidebarId: 'docs', position: 'left', label: 'Docs' },
          { to: 'savings', label: 'Savings', position: 'left' },
          { to: 'blog', label: 'Blog', position: 'left' },
          {
            href: 'https://github.com/carefreeinv/anchor',
            label: 'GitHub',
            position: 'right',
          },
          {
            href: 'https://donate.stripe.com/28E6oHeq8fxQ5p7fmBdjO01',
            label: 'Donate',
            position: 'right',
            className: 'navbar-donate-link',
          },
        ],
      },
      footer: {
        style: 'dark',
        links: [
          {
            title: 'Anchor',
            items: [
              {
                label: 'Savings',
                to: 'savings',
              },
              {
                label: 'GitHub',
                href: 'https://github.com/carefreeinv/anchor',
              },
              {
                label: 'Donate',
                href: 'https://donate.stripe.com/28E6oHeq8fxQ5p7fmBdjO01',
              },
            ],
          },
          {
            title: 'About',
            items: [
              {
                label: 'Carefree Investments LLC',
                href: 'https://carefreeinv.com',
              },
            ],
          },
        ],
        copyright:
          'Anchor — orchestrate cheap models with expensive judgment.<br />An open-source project by <a href="https://carefreeinv.com">Carefree Investments LLC</a>. Source on <a href="https://github.com/carefreeinv/anchor">GitHub</a>.',
      },
      colorMode: { defaultMode: 'dark' },
      mermaid: {
        theme: { light: 'neutral', dark: 'dark' },
        // Fixed series colors so page legends can match line/bar strokes
        options: {
          themeVariables: {
            xyChart: {
              plotColorPalette:
                '#4e79a7,#f28e2b,#59a14f,#e15759,#b07aa1,#edc948,#76b7b2,#ff9da7',
            },
          },
        },
      },
    }),
};

export default config;
