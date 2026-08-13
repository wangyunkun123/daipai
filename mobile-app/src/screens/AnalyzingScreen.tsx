import React, { useEffect, useRef, useState } from 'react';
import { View, Text, StyleSheet, Image } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, fonts, fontSizes, spacing, radii } from '../theme/tokens';
import { PhaseIndicator } from '../components/PhaseIndicator';
import { readPhotoAsBase64, analyzeStream } from '../api/client';
import { useSessionStore } from '../store/useSessionStore';
import { saveSession } from '../storage/session';
import type { RootStackParamList } from '../navigation/AppNavigator';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import type { RouteProp } from '@react-navigation/native';

type Nav = NativeStackNavigationProp<RootStackParamList, 'Analyzing'>;
type Rt = RouteProp<RootStackParamList, 'Analyzing'>;

const PHASE_MAP: Record<string, number> = {
  exif: 1,
  vision: 2,
  directions: 3,
  plans: 3,
};

export function AnalyzingScreen() {
  const navigation = useNavigation<Nav>();
  const route = useRoute<Rt>();
  const { photoPath, device } = route.params;

  const setExif = useSessionStore(s => s.setExif);
  const setVision = useSessionStore(s => s.setVision);
  const setDirections = useSessionStore(s => s.setDirections);
  const [phase, setPhase] = useState(0);
  const [failed, setFailed] = useState<string | null>(null);
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    let cancelled = false;
    (async () => {
      try {
        const base64 = await readPhotoAsBase64(photoPath);
        await analyzeStream(
          { photoBase64: base64, device },
          e => {
            if (cancelled) return;
            switch (e.event) {
              case 'progress':
                setPhase(p => PHASE_MAP[e.phase] ?? p);
                break;
              case 'exif_ready':
                setPhase(1);
                setExif(e.data);
                break;
              case 'vision_ready':
                setPhase(2);
                setVision(e.data);
                break;
              case 'directions_ready': {
                setPhase(3);
                const dirs = e.data.directions ?? [];
                const sessionId = e.data.session_id;
                setDirections(dirs, sessionId);
                // 落库
                saveSession({
                  session_id: sessionId,
                  photo_path: photoPath,
                  device: device ?? null,
                  exif_json: JSON.stringify(useSessionStore.getState().exif ?? {}),
                  vision_json: JSON.stringify(useSessionStore.getState().vision ?? {}),
                  directions_json: JSON.stringify(dirs),
                  created_at: Date.now(),
                }).catch(() => {});
                setTimeout(() => {
                  if (!cancelled) navigation.replace('Directions');
                }, 600);
                break;
              }
              case 'complete':
                // directions_ready 已导航；complete 兜底
                break;
              case 'error':
                // 内联展示失败（下方 failed 视图 + 点击返回），不再弹 Alert——
                // 否则 analyzeStream 会 reject，外层 catch 再弹一次，双弹窗。
                setFailed(e.data.message);
                break;
              default:
                break;
            }
          },
        );
      } catch (e: any) {
        if (!cancelled) {
          setFailed(e?.message ?? '网络错误');
        }
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [photoPath, device]);

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.content}>
        <Image
          source={{ uri: `file://${photoPath.replace('file://', '')}` }}
          style={styles.thumb}
          resizeMode="cover"
        />
        <View style={styles.indicatorWrap}>
          <PhaseIndicator phaseIndex={failed != null ? 0 : phase} />
          {failed != null && (
            <View style={styles.failedWrap}>
              <Text style={styles.failedText}>{failed}</Text>
              <Text style={styles.failedSub} onPress={() => navigation.goBack()}>
                点击返回重拍
              </Text>
            </View>
          )}
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.cream },
  content: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.xl,
  },
  thumb: {
    width: 200,
    height: 260,
    borderRadius: radii.card,
    marginBottom: spacing.xxxl,
    backgroundColor: colors.mist,
  },
  indicatorWrap: { width: '100%', alignItems: 'center' },
  failedWrap: { marginTop: spacing.xl, alignItems: 'center' },
  failedText: {
    fontFamily: fonts.sans,
    fontSize: fontSizes.body,
    color: colors.danger,
    textAlign: 'center',
  },
  failedSub: {
    fontFamily: fonts.sans,
    fontSize: fontSizes.small,
    color: colors.hujia,
    marginTop: spacing.s,
    textDecorationLine: 'underline',
  },
});
