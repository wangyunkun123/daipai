import React from 'react';
import { View, Text, StyleSheet, ScrollView, Dimensions } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, fonts, fontSizes, spacing } from '../theme/tokens';
import { DirectionCard } from '../components/DirectionCard';
import { useSessionStore } from '../store/useSessionStore';
import type { RootStackParamList } from '../navigation/AppNavigator';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';

type Nav = NativeStackNavigationProp<RootStackParamList>;
const { width } = Dimensions.get('window');

export function DirectionsScreen() {
  const navigation = useNavigation<Nav>();
  const directions = useSessionStore(s => s.directions);

  if (!directions.length) {
    return (
      <SafeAreaView style={styles.safe}>
        <Text style={styles.empty}>没有生成方向，请返回重拍。</Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'bottom']}>
      <Text style={styles.heading}>三个拍法</Text>
      <Text style={styles.subheading}>左右滑动挑一个</Text>
      <ScrollView
        horizontal
        pagingEnabled
        snapToInterval={336} // card 320 + margin 16
        decelerationRate="fast"
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.scroll}
      >
        {directions.map(d => (
          <DirectionCard
            key={d.id || d.style}
            direction={d}
            onSeePlans={() =>
              navigation.navigate('Plans', {
                directionId: d.id,
                directionTitle: d.style,
              })
            }
          />
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.cream },
  heading: {
    fontFamily: fonts.serif,
    fontSize: fontSizes.h1,
    color: colors.ink,
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.m,
  },
  subheading: {
    fontFamily: fonts.sans,
    fontSize: fontSizes.small,
    color: colors.stone,
    paddingHorizontal: spacing.xl,
    marginBottom: spacing.xl,
  },
  scroll: { paddingHorizontal: (width - 320) / 2 - spacing.m, paddingVertical: spacing.l },
  empty: {
    fontFamily: fonts.sans,
    fontSize: fontSizes.body,
    color: colors.stone,
    textAlign: 'center',
    marginTop: 100,
  },
});
