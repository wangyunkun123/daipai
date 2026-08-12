import React, { useRef, useState, useEffect } from 'react';
import { View, StyleSheet, Pressable, Text, Alert } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  Camera,
  useCameraDevice,
  useCameraPermission,
  type PhotoFile,
} from 'react-native-vision-camera';
import DeviceInfo from 'react-native-device-info';
import { X, RefreshCw } from 'lucide-react-native';
import { colors, fonts, spacing } from '../theme/tokens';
import { useSessionStore } from '../store/useSessionStore';
import type { RootStackParamList } from '../navigation/AppNavigator';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';

type Nav = NativeStackNavigationProp<RootStackParamList, 'Camera'>;

export function CameraScreen() {
  const navigation = useNavigation<Nav>();
  const { hasPermission, requestPermission } = useCameraPermission();
  const cameraRef = useRef<Camera>(null);
  const setPhoto = useSessionStore(s => s.setPhoto);
  const [taking, setTaking] = useState(false);
  const [position, setPosition] = useState<'back' | 'front'>('back');
  const currentDevice = useCameraDevice(position);

  useEffect(() => {
    if (hasPermission === false) {
      requestPermission();
    }
  }, [hasPermission, requestPermission]);

  const takePhoto = async () => {
    if (!cameraRef.current || taking) return;
    setTaking(true);
    try {
      const photo: PhotoFile = await cameraRef.current.takePhoto({
        flash: 'off',
        enableShutterSound: true,
      });
      setPhoto(photo.path);
      const model = DeviceInfo.getModel(); // e.g. "iPhone 15 Pro"
      navigation.replace('Analyzing', {
        photoPath: photo.path,
        device: model,
      });
    } catch (e: any) {
      Alert.alert('拍照失败', e?.message ?? '请重试');
    } finally {
      setTaking(false);
    }
  };

  if (hasPermission === false) {
    return (
      <SafeAreaView style={styles.permWrap}>
        <Text style={styles.permText}>需要相机权限才能带拍</Text>
        <Pressable onPress={requestPermission} style={styles.permBtn}>
          <Text style={styles.permBtnText}>去开启</Text>
        </Pressable>
      </SafeAreaView>
    );
  }

  if (currentDevice == null) {
    return <View style={styles.black} />;
  }

  return (
    <View style={styles.container}>
      <Camera
        ref={cameraRef}
        style={StyleSheet.absoluteFill}
        device={currentDevice}
        isActive={true}
        photo={true}
        enableZoomGesture={false}
      />
      <SafeAreaView style={styles.ui} edges={['top', 'bottom']}>
        <View style={styles.topBar}>
          <Pressable
            onPress={() => navigation.goBack()}
            hitSlop={12}
            accessibilityLabel="关闭相机"
          >
            <X color={colors.guideWhite} size={26} />
          </Pressable>
          <Pressable
            onPress={() => setPosition(p => (p === 'back' ? 'front' : 'back'))}
            hitSlop={12}
            accessibilityLabel="切换摄像头"
          >
            <RefreshCw color={colors.guideWhite} size={24} />
          </Pressable>
        </View>

        <View style={styles.bottomBar}>
          <Pressable
            onPress={takePhoto}
            disabled={taking}
            accessibilityRole="button"
            accessibilityLabel="拍照"
            style={({ pressed }) => [styles.shutter, pressed && styles.shutterPressed]}
          >
            <View style={styles.shutterRing} />
          </Pressable>
        </View>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.viewfinderBg },
  black: { flex: 1, backgroundColor: colors.viewfinderBg },
  ui: { flex: 1, justifyContent: 'space-between' },
  topBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    padding: spacing.l,
  },
  bottomBar: { alignItems: 'center', paddingBottom: spacing.xl },
  shutter: {
    width: 84,
    height: 84,
    borderRadius: 42,
    alignItems: 'center',
    justifyContent: 'center',
  },
  shutterRing: {
    width: 72,
    height: 72,
    borderRadius: 36,
    borderWidth: 4,
    borderColor: colors.guideWhite,
    backgroundColor: 'transparent',
  },
  shutterPressed: { opacity: 0.7, transform: [{ scale: 0.96 }] },
  permWrap: {
    flex: 1,
    backgroundColor: colors.cream,
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.xl,
  },
  permText: {
    fontFamily: fonts.sans,
    fontSize: 16,
    color: colors.ink,
    marginBottom: spacing.l,
  },
  permBtn: {
    backgroundColor: colors.hujia,
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.m,
    borderRadius: 16,
  },
  permBtnText: { color: colors.paper, fontFamily: fonts.sans, fontWeight: '600' },
});
