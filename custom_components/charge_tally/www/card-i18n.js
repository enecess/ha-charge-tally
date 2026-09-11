import en from './locales/en.js?v=0.1.2';
import zhHans from './locales/zh-Hans.js?v=0.1.2';
import de from './locales/de.js?v=0.1.2';
import fr from './locales/fr.js?v=0.1.2';
import pl from './locales/pl.js?v=0.1.2';

const catalogs = {en, 'zh-Hans': zhHans, de, fr, pl};

export function locale(language) {
  try {
    return Intl.getCanonicalLocales(typeof language === 'string' ? language.replaceAll('_', '-') : '')[0] || 'en';
  } catch {
    return 'en';
  }
}

export function tr(key, language = 'en', values = {}) {
  const tag = locale(language);
  const base = tag.split('-')[0];
  const catalog = catalogs[tag] || catalogs[base === 'zh' ? 'zh-Hans' : base] || en;
  const message = (Object.hasOwn(catalog, key) && catalog[key]) || (Object.hasOwn(en, key) && en[key]) || key;
  // Return plain text; DOM consumers use textContent and never interpret HTML.
  return message.replace(/\{(\w+)\}/g, (placeholder, name) => Object.hasOwn(values, name) ? String(values[name]) : placeholder);
}
