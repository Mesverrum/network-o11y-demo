import { AppPlugin } from '@grafana/data';
import DevicesHome from './pages/DevicesHome';

export const plugin = new AppPlugin<{}>().setRootPage(DevicesHome);
