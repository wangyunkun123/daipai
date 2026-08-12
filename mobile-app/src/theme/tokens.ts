/**
 * 带拍 APP 设计 Token —— 奶油胶片杂志 Cream Film Editorial
 * 唯一真相源。组件禁止硬编码颜色/字号/圆角。
 */

export const colors = {
  // 内容态（奶油底）
  cream: '#FAF6F0',
  ink: '#1C1917',
  hujia: '#B5673E', // 焙茶褐，主色
  gold: '#C9A063', // 暖金箔，强调/引导
  stone: '#78716C', // 次要文字
  paper: '#FFFFFF', // 卡片
  line: '#EDE6DB', // 极淡描边
  mist: '#F3EDE3', // 次级背景

  // 三方向状态色（低饱和，奶油底和谐）
  now: '#7C8A5E', // 🟢 苔藓绿，现在就拍
  best: '#D98248', // 🔥 焙茶橙，最出片
  creative: '#9B8AB4', // ✨ 灰紫，最大胆

  // 取景器态
  viewfinderBg: '#0D0D0D',
  guideGold: '#C9A063',
  guideWhite: 'rgba(255,255,255,0.85)',
  zebra: 'rgba(255,255,255,0.35)',

  // 后期态
  darkroomBg: '#161412',
  darkroomFg: '#F5EDE0',

  // 功能色
  success: '#7C8A5E',
  warning: '#D98248',
  danger: '#C0504A',
  info: '#7A8B99',
} as const;

export const fonts = {
  // 标题：iOS 系统衬线（New York），杂志感。v0.2 换打包的思源宋体
  serif: 'ui-serif',
  // 正文：系统无衬线（iOS 自动落苹方 PingFang SC）
  sans: 'ui-sans-serif',
  // 数字等宽（EV/ISO/焦段跳动时不晃）
  mono: 'ui-monospace',
} as const;

export const fontSizes = {
  hero: 34,
  h1: 28,
  h2: 20,
  body: 15,
  small: 13,
  caption: 11,
} as const;

export const lineHeights = {
  tight: 1.2,
  normal: 1.5,
  loose: 1.7,
} as const;

export const spacing = {
  xs: 4,
  s: 8,
  m: 12,
  l: 16,
  xl: 24,
  xxl: 32,
  xxxl: 48,
} as const;

// 层级分明，不全站一个圆角
export const radii = {
  tag: 10,
  input: 14,
  button: 16,
  card: 22,
} as const;

export const shadows = {
  card: {
    shadowColor: '#1C1917',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.06,
    shadowRadius: 30,
    elevation: 0,
  },
  button: {
    shadowColor: '#B5673E',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.25,
    shadowRadius: 12,
    elevation: 0,
  },
} as const;
