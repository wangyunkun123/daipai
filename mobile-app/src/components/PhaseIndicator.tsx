import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Canvas, Line } from '@shopify/react-native-skia';
import { colors, fonts, fontSizes, spacing } from '../theme/tokens';

const PHASES = [
  '正在看你的照片…',
  '识别光线和场景…',
  '想几个拍法…',
  '整理成方案…',
];

export function PhaseIndicator({ phaseIndex }: { phaseIndex: number }) {
  const clamped = Math.min(Math.max(phaseIndex, 0), PHASES.length);
  const progress = clamped / PHASES.length;
  const message = PHASES[Math.min(clamped, PHASES.length - 1)];

  return (
    <View style={styles.wrap}>
      <Canvas style={styles.bar}>
        <Line p1={{ x: 0, y: 6 }} p2={{ x: 280, y: 6 }} color={colors.line} strokeWidth={4} />
        <Line
          p1={{ x: 0, y: 6 }}
          p2={{ x: 280 * progress, y: 6 }}
          color={colors.hujia}
          strokeWidth={4}
        />
      </Canvas>
      <Text style={styles.text}>{message}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: 'center' },
  bar: { width: 280, height: 16 },
  text: {
    fontFamily: fonts.serif,
    fontSize: fontSizes.h2,
    color: colors.ink,
    marginTop: spacing.xl,
    textAlign: 'center',
  },
});
