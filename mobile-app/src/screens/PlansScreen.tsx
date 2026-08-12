import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import { useRoute } from '@react-navigation/native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, fonts, fontSizes, spacing } from '../theme/tokens';
import { PlanCard } from '../components/PlanCard';
import { fetchPlans } from '../api/client';
import { useSessionStore } from '../store/useSessionStore';
import type { Plan } from '../api/types';
import type { RouteProp } from '@react-navigation/native';
import type { RootStackParamList } from '../navigation/AppNavigator';

type Rt = RouteProp<RootStackParamList, 'Plans'>;

export function PlansScreen() {
  const { directionId, directionTitle } = useRoute<Rt>().params;
  const sessionId = useSessionStore(s => s.sessionId);
  const device = useSessionStore(s => s.device);
  const photoPath = useSessionStore(s => s.photoPath);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    if (!sessionId) {
      setError('会话已过期');
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const list = await fetchPlans({
        sessionId,
        directionId,
        device: device ?? undefined,
      });
      setPlans(list);
    } catch (e: any) {
      setError(e?.message ?? '加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'bottom']}>
      <Text style={styles.title}>{directionTitle}</Text>
      <Text style={styles.sub}>
        {plans.length > 0 ? `${plans.length} 套方案` : '加载方案中…'}
      </Text>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.hujia} size="large" />
        </View>
      ) : error ? (
        <View style={styles.center}>
          <Text style={styles.err}>{error}</Text>
          <Text style={styles.retry} onPress={load}>
            点此重试
          </Text>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.hujia} />
          }
        >
          {photoPath &&
            plans.map((p, i) => <PlanCard key={i} plan={p} photoPath={photoPath} />)}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.cream },
  title: {
    fontFamily: fonts.serif,
    fontSize: fontSizes.h1,
    color: colors.ink,
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.m,
  },
  sub: {
    fontFamily: fonts.sans,
    fontSize: fontSizes.small,
    color: colors.stone,
    paddingHorizontal: spacing.xl,
    marginBottom: spacing.l,
  },
  list: { padding: spacing.xl, paddingBottom: spacing.xxxl },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  err: { fontFamily: fonts.sans, color: colors.danger, marginBottom: spacing.m },
  retry: {
    fontFamily: fonts.sans,
    color: colors.hujia,
    textDecorationLine: 'underline',
  },
});
