import React from 'react';
import CorporateLogo from '@/components/logo.jsx';

// Affiliation logos, side by side on the page's white background rather than in
// the gray header: the U-Tokyo mark is fixed-color artwork, so it cannot be
// inverted with the theme the way the SINIC X wordmark is.
//
// The U-Tokyo file lives in `public/`, so it is referenced by relative URL (like
// the teaser) instead of imported — `base: './'` keeps that correct on both root
// and subpath deploys.
export default class AffiliationLogos extends React.Component {
  render() {
    return (
      <div
        className="uk-flex uk-flex-center uk-flex-middle uk-flex-wrap"
        style={{ gap: '28px', padding: '20px 0 8px' }}
      >
        <a href="https://www.u-tokyo.ac.jp/en/" target="_blank">
          <img
            src="utokyo.svg"
            alt="The University of Tokyo"
            style={{ height: '78px' }}
          />
        </a>
        <a href="https://www.omron.com/sinicx" target="_blank">
          <CorporateLogo size="xxl" />
        </a>
      </div>
    );
  }
}
