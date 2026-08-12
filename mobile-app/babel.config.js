module.exports = {
  presets: ['module:@react-native/babel-preset'],
  plugins: [
    [
      'module:react-native-dotenv',
      {
        moduleName: '@env',
        path: '.env',
        safe: true,
        allowUndefined: false,
      },
    ],
    // react-native-worklets/plugin 必须放在最后（reanimated v4 + skia 依赖 worklets）
    'react-native-worklets/plugin',
  ],
};
