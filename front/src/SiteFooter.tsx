import './SiteFooter.css'

const DEVELOPER_LINK =
  'https://www.linkedin.com/in/mohammad-javad-moghofei-907671214/'

export default function SiteFooter() {
  return (
    <footer className="site-footer" lang="en" dir="ltr">
      <p>
        Developed by{' '}
        <a
          className="site-footer-brand"
          href={DEVELOPER_LINK}
          target="_blank"
          rel="noopener noreferrer"
        >
          ThisJ
        </a>
      </p>
    </footer>
  )
}