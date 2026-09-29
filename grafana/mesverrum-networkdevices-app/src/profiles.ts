import baked from './profiles.json';

export type Profile = {
  name: string;
  hot: string[];
  cold: string[];
  topology: string[];
};

export type ProfileCatalog = {
  fingerprinter: string;
  library_hash: string;
  source: string;
  profiles: Profile[];
  /** Where the picker got this list. */
  origin: 'collector' | 'plugin';
};

const BAKED = baked as Omit<ProfileCatalog, 'origin'>;

export function bakedCatalog(): ProfileCatalog {
  return { ...BAKED, profiles: BAKED.profiles, origin: 'plugin' };
}

export function profileByName(catalog: ProfileCatalog, name: string): Profile | undefined {
  return catalog.profiles.find((profile) => profile.name === name);
}

function norm(value: string): string {
  return value
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
    .join(',');
}

/** The catalog profile whose three lists match, or empty when the fields are a fingerprint or a hand edit. */
export function matchingProfile(catalog: ProfileCatalog, hot: string, cold: string, topology: string): string {
  const h = norm(hot);
  const c = norm(cold);
  const t = norm(topology);
  if (!h && !c && !t) {
    return '';
  }
  const hit = catalog.profiles.find(
    (profile) => norm(profile.hot.join(',')) === h && norm(profile.cold.join(',')) === c && norm(profile.topology.join(',')) === t
  );
  return hit?.name || '';
}

export function profileLabel(catalog: ProfileCatalog, hot: string, cold: string, topology: string): string {
  const name = matchingProfile(catalog, hot, cold, topology);
  if (name) {
    return name;
  }
  if (hot || cold || topology) {
    return 'custom';
  }
  return '';
}
