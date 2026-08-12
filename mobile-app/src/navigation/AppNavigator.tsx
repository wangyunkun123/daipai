import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { Camera as CameraIcon, Sparkles, Images, User } from 'lucide-react-native';
import { colors, fonts } from '../theme/tokens';

import { HomeScreen } from '../screens/HomeScreen';
import { CameraScreen } from '../screens/CameraScreen';
import { AnalyzingScreen } from '../screens/AnalyzingScreen';
import { DirectionsScreen } from '../screens/DirectionsScreen';
import { PlansScreen } from '../screens/PlansScreen';
import { InspirationScreen, GalleryScreen, ProfileScreen } from '../screens/PlaceholderScreens';

export type RootStackParamList = {
  Tabs: undefined;
  Camera: undefined;
  Analyzing: { photoPath: string; device?: string };
  Directions: undefined;
  Plans: { directionId: string; directionTitle: string };
};

const Tab = createBottomTabNavigator();
const Stack = createNativeStackNavigator<RootStackParamList>();

function Tabs() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarActiveTintColor: colors.hujia,
        tabBarInactiveTintColor: colors.stone,
        tabBarStyle: {
          backgroundColor: colors.cream,
          borderTopColor: colors.line,
          height: 82,
          paddingBottom: 20,
        },
        tabBarLabelStyle: { fontSize: 11, fontFamily: fonts.sans },
        tabBarIcon: ({ color, size }) => {
          const icons = {
            Home: CameraIcon,
            Inspiration: Sparkles,
            Gallery: Images,
            Profile: User,
          } as const;
          const Icon = icons[route.name as keyof typeof icons] ?? CameraIcon;
          return <Icon color={color} size={size ?? 24} />;
        },
      })}
    >
      <Tab.Screen name="Home" component={HomeScreen} options={{ title: '拍' }} />
      <Tab.Screen name="Inspiration" component={InspirationScreen} options={{ title: '灵感' }} />
      <Tab.Screen name="Gallery" component={GalleryScreen} options={{ title: '作品' }} />
      <Tab.Screen name="Profile" component={ProfileScreen} options={{ title: '我的' }} />
    </Tab.Navigator>
  );
}

export function AppNavigator() {
  return (
    <NavigationContainer>
      <Stack.Navigator screenOptions={{ headerShown: false }}>
        <Stack.Screen name="Tabs" component={Tabs} />
        <Stack.Screen
          name="Camera"
          component={CameraScreen}
          options={{ presentation: 'fullScreenModal', animation: 'slide_from_bottom' }}
        />
        <Stack.Screen name="Analyzing" component={AnalyzingScreen} />
        <Stack.Screen name="Directions" component={DirectionsScreen} />
        <Stack.Screen name="Plans" component={PlansScreen} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}
