import React from 'react';

export default class Footer extends React.Component {
  constructor(props) {
    super(props);
  }
  render() {
    return (
      <div className="uk-text-center uk-text-meta">
        <a href="https://www.omron.com/sinicx/" target="_blank">
          <span>© 2026 OMRON SINIC X Corporation, all rights reserved.</span>
        </a>
      </div>
    );
  }
}
