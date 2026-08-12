import React, { useState } from 'react';
import { View, Text, StyleSheet, Image, Dimensions } from 'react-native';
import { colors, fonts, fontSizes, spacing, radii, shadows } from '../theme/tokens';
import { SketchAnnotation } from './SketchAnnotation';
import type { Plan } from '../api/types';

const IMG_W = Dimensions.get('window').width - spacing.xl * 2;
const IMG_H = IMG_W * 1.3;

export function PlanCard({ plan, photoPath }: { plan: Plan; photoPath: string }) {
  const [loaded, setLoaded] = useState(false);
  return (
    <View style={styles.card}>
      <View style={[styles.imgWrap, { width: IMG_W, height: IMG_H }]}>
        <Image
          source={{ uri: `file://${photoPath.replace('file://', '')}` }}
          style={StyleSheet.absoluteFill}
          resizeMode="cover"
          onLoad={() => setLoaded(true)}
        />
        {loaded && (
          <SketchAnnotation width={IMG_W} height={IMG_H} annotations={plan.annotations} />
        )}
      </View>

      <Text style={styles.name}>{plan.name}</Text>
      {(plan.shot_size || plan.angle) && (
        <Text style={styles.tags}>{[plan.shot_size, plan.angle].filter(Boolean).join(' · ')}</Text>
      )}

      <Section label="被拍摄者" text={plan.subject} />
      <Section label="摄影师" text={plan.shooter} />
      <Section label="设备调试" text={plan.gear} />
      <Section label="现场增色" text={plan.enhance} />
      <Section label="画面效果" text={plan.result} gold />
      {plan.why ? <Section label="为什么好看" text={plan.why} muted /> : null}
    </View>
  );
}

function Section({
  label,
  text,
  gold,
  muted,
}: {
  label: string;
  text: string;
  gold?: boolean;
  muted?: boolean;
}) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionLabel}>{label}</Text>
      <Text style={[styles.sectionText, gold && styles.goldText, muted && styles.mutedText]}>
        {text}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.paper,
    borderRadius: radii.card,
    padding: spacing.l,
    marginBottom: spacing.xl,
    ...shadows.card,
  },
  imgWrap: { borderRadius: radii.input, overflow: 'hidden', backgroundColor: colors.mist },
  name: { fontFamily: fonts.serif, fontSize: fontSizes.h2, color: colors.ink, marginTop: spacing.l },
  tags: {
    fontFamily: fonts.sans,
    fontSize: fontSizes.small,
    color: colors.gold,
    marginTop: spacing.xs,
  },
  section: { marginTop: spacing.m },
  sectionLabel: {
    fontFamily: fonts.sans,
    fontSize: fontSizes.caption,
    color: colors.stone,
    letterSpacing: 1,
    textTransform: 'uppercase',
    marginBottom: 2,
  },
  sectionText: { fontFamily: fonts.sans, fontSize: fontSizes.body, color: colors.ink, lineHeight: 24 },
  goldText: { color: colors.hujia, fontFamily: fonts.serif, fontSize: fontSizes.body },
  mutedText: { color: colors.stone, fontStyle: 'italic' },
});
