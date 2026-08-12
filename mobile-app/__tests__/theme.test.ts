import { colors, radii } from '../src/theme/tokens';

describe('design tokens', () => {
  it('uses the cream film editorial palette', () => {
    expect(colors.cream).toBe('#FAF6F0');
    expect(colors.hujia).toBe('#B5673E');
    expect(colors.gold).toBe('#C9A063');
  });

  it('uses layered radii, not a single value', () => {
    expect(radii.card).toBeGreaterThan(radii.button);
    expect(radii.button).toBeGreaterThan(radii.tag);
  });
});
