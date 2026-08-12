import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors, fonts, fontSizes, spacing, radii, shadows } from '../theme/tokens';
import { CreamButton } from './CreamButton';
import type { Direction } from '../api/types';

const SLOT_META = {
  now: { label: '🟢 现在就拍', color: colors.now, en: 'RIGHT NOW' },
  best: { label: '🔥 最出片', color: colors.best, en: 'THE SHOT' },
  creative: { label: '✨ 最大胆', color: colors.creative, en: 'BOLD MOVE' },
} as const;

export function DirectionCard({
  direction,
  onSeePlans,
}: {
  direction: Direction;
  onSeePlans: () => void;
}) {
  const meta = SLOT_META[direction.id] ?? SLOT_META.now;
  return (
    <View style={styles.card}>
      <View style={[styles.badge, { backgroundColor: `${meta.color}22` }]}>
        <Text style={[styles.badgeText, { color: meta.color }]}>{meta.label}</Text>
      </View>

      <Text style={styles.en}>{meta.en}</Text>
      <Text style={styles.title}>{direction.style}</Text>
      <Text style={styles.promise}>{direction.style_promise}</Text>

      {direction.reason ? <Text style={styles.reason}>{direction.reason}</Text> : null}

      <View style={styles.notes}>
        {direction.light_annotation ? (
          <View style={styles.noteRow}>
            <Text style={styles.noteLabel}>光线</Text>
            <Text style={styles.noteVal}>{direction.light_annotation}</Text>
          </View>
        ) : null}
        {direction.device_annotation ? (
          <View style={styles.noteRow}>
            <Text style={styles.noteLabel}>设备</Text>
            <Text style={styles.noteVal}>{direction.device_annotation}</Text>
          </View>
        ) : null}
      </View>

      <CreamButton
        title={`看 ${direction.plans?.length ?? '?'} 套方案`}
        onPress={onSeePlans}
        style={styles.btn}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    width: 320,
    minHeight: 480,
    backgroundColor: colors.paper,
    borderRadius: radii.card,
    padding: spacing.xl,
    marginHorizontal: spacing.m,
    ...shadows.card,
    justifyContent: 'space-between',
  },
  badge: {
    alignSelf: 'flex-start',
    paddingHorizontal: spacing.m,
    paddingVertical: spacing.xs,
    borderRadius: radii.tag,
  },
  badgeText: { fontFamily: fonts.sans, fontSize: fontSizes.caption, fontWeight: '600' },
  en: {
    fontFamily: fonts.serif,
    fontStyle: 'italic',
    fontSize: fontSizes.caption,
    color: colors.gold,
    letterSpacing: 2,
    marginTop: spacing.l,
  },
  title: { fontFamily: fonts.serif, fontSize: fontSizes.h1, color: colors.ink, marginTop: spacing.xs },
  promise: {
    fontFamily: fonts.serif,
    fontSize: fontSizes.h2,
    color: colors.ink,
    lineHeight: 30,
    marginTop: spacing.m,
  },
  reason: {
    fontFamily: fonts.sans,
    fontSize: fontSizes.body,
    color: colors.stone,
    marginTop: spacing.m,
    lineHeight: 24,
  },
  notes: { marginTop: spacing.l, gap: spacing.s },
  noteRow: { flexDirection: 'row', gap: spacing.m },
  noteLabel: { fontFamily: fonts.sans, fontSize: fontSizes.small, color: colors.stone, width: 40 },
  noteVal: { flex: 1, fontFamily: fonts.sans, fontSize: fontSizes.small, color: colors.ink },
  btn: { marginTop: spacing.xl, width: '100%' },
});
