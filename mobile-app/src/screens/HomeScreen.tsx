import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  type NativeSyntheticEvent,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, fonts, fontSizes, spacing, radii, shadows } from '../theme/tokens';
import { CreamButton } from '../components/CreamButton';
import { useSessionStore } from '../store/useSessionStore';
import { getRecentSessions, type SessionRow } from '../storage/session';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import type { RootStackParamList } from '../navigation/AppNavigator';

type Nav = NativeStackNavigationProp<RootStackParamList>;

export function HomeScreen() {
  const navigation = useNavigation<Nav>();
  const reset = useSessionStore(s => s.reset);
  const [recent, setRecent] = useState<SessionRow[]>([]);

  useEffect(() => {
    getRecentSessions(6)
      .then(setRecent)
      .catch(() => {});
  }, []);

  const start = () => {
    reset();
    navigation.navigate('Camera');
  };

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.brand}>带拍</Text>
        <Text style={styles.slogan}>去了不会拍？带你拍。</Text>

        <View style={styles.hero}>
          <Text style={styles.heroTitle}>今天的光</Text>
          <Text style={styles.heroSub}>v0.2 接入位置与黄金时刻</Text>
        </View>

        <CreamButton title="开始拍" onPress={start} style={styles.cta} />

        {recent.length > 0 && (
          <View style={styles.recentWrap}>
            <Text style={styles.sectionTitle}>最近的方案</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false}>
              {recent.map(s => {
                let title = '未命名场景';
                try {
                  const dirs = JSON.parse(s.directions_json ?? '[]');
                  title = dirs[0]?.style ?? title;
                } catch {}
                return (
                  <Pressable key={s.session_id} style={styles.recentCard}>
                    <Text style={styles.recentCardTitle} numberOfLines={2}>
                      {title}
                    </Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.cream },
  content: { padding: spacing.xl, paddingBottom: spacing.xxxl },
  brand: {
    fontFamily: fonts.serif,
    fontSize: 40,
    color: colors.ink,
    marginTop: spacing.m,
    letterSpacing: 2,
  },
  slogan: {
    fontFamily: fonts.sans,
    fontSize: fontSizes.small,
    color: colors.stone,
    marginTop: spacing.xs,
    letterSpacing: 0.5,
  },
  hero: {
    backgroundColor: colors.paper,
    borderRadius: radii.card,
    padding: spacing.xl,
    marginTop: spacing.xxl,
    ...shadows.card,
  },
  heroTitle: { fontFamily: fonts.serif, fontSize: fontSizes.h2, color: colors.ink },
  heroSub: {
    fontFamily: fonts.sans,
    fontSize: fontSizes.small,
    color: colors.stone,
    marginTop: spacing.s,
  },
  cta: { marginTop: spacing.xl },
  recentWrap: { marginTop: spacing.xxxl },
  sectionTitle: {
    fontFamily: fonts.sans,
    fontSize: fontSizes.small,
    color: colors.stone,
    letterSpacing: 1,
    textTransform: 'uppercase',
    marginBottom: spacing.m,
  },
  recentCard: {
    width: 140,
    height: 180,
    backgroundColor: colors.paper,
    borderRadius: radii.card,
    padding: spacing.m,
    marginRight: spacing.m,
    justifyContent: 'flex-end',
    ...shadows.card,
  },
  recentCardTitle: { fontFamily: fonts.serif, fontSize: fontSizes.body, color: colors.ink },
});
