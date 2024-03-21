// import from file `services/browser.ts`
import { type BrowserService } from 'services/browser';

// import everything from deployment
import * from "deployment"

// import from 3rd party packages, ignored
import { type foo, type bar } from 'redux'
import * as Sentry from '@sentry/react';

// local file import
import { dispatcher } from './dispatcher';
import { receiver } from './receiver';
