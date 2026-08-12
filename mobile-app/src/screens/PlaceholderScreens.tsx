import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors, fonts, fontSizes, spacing } from '../theme/tokens';

function Placeholder({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <View style={styles.wrap}>
      <Text style={styles.title}>{title}</Text>
      <Text style={styles.subtitle}>{subtitle}</Text>
    </View>
  );
}

export const InspirationScreen = () => (
  <Placeholder title="灵感" subtitle="v0.2：风格库与场景教程" />
);
export const GalleryScreen = () => (
  <Placeholder title="作品" subtitle="v0.2：你拍过的照片和方案" />
);
export const ProfileScreen = () => (
  <Placeholder title="我的" subtitle="设置、配额、反馈" />
);

const styles = StyleSheet.create({
  wrap: {
    flex: 1,
    backgroundColor: colors.cream,
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.xl,
  },
  title: { fontFamily: fonts.serif, fontSize: fontSizes.h1, color: colors.ink, marginBottom: spacing.s },
  subtitle: { fontFamily: fonts.sans, fontSize: fontSizes.body, color: colors.stone },
});
