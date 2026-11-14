// FIT 枚举数值 → 字符串名（对齐桌面端 fitparse 的字符串取值）
//
// ⚠️ 为什么需要这个文件：
//   桌面端用 `fitparse`，`session.sub_sport` 直接给的是**字符串**（如 "road"）。
//   移动端用 `activity_files`，`ActivitySummary.subSport` 给的是**FIT 枚举数值**（int）。
//   桌面端 core/fit_parser.py:320 的 SUB_SPORT_CN 以字符串为键，
//   所以移动端必须先做「数值 → 字符串」还原，才能复用同一张中文表。
//
// 数值来源：桌面端 venv 内 `fitparse.profile.FIELD_TYPES['sub_sport'].values`
//          （= FIT SDK Profile.xlsx 官方枚举，共 61 项）。
// 生成命令（可复现）：
//   cd fit_analyzer && .venv/Scripts/python.exe -c "import fitparse.profile as P; t=P.FIELD_TYPES['sub_sport']; [print(f'{k}: \x27{t.values[k]}\x27,') for k in sorted(t.values)]"
//
// 未收录的数值 → null（不给名字），上层会退化成空串，与桌面端
// `sub_sport = sget("sub_sport") or ""` 的「未知即空」行为一致。

/// FIT `sub_sport` 枚举值 → 名称（与 fitparse 输出逐字一致）。
const Map<int, String> kFitSubSportNames = {
  0: 'generic',
  1: 'treadmill',
  2: 'street',
  3: 'trail',
  4: 'track',
  5: 'spin',
  6: 'indoor_cycling',
  7: 'road',
  8: 'mountain',
  9: 'downhill',
  10: 'recumbent',
  11: 'cyclocross',
  12: 'hand_cycling',
  13: 'track_cycling',
  14: 'indoor_rowing',
  15: 'elliptical',
  16: 'stair_climbing',
  17: 'lap_swimming',
  18: 'open_water',
  19: 'flexibility_training',
  20: 'strength_training',
  21: 'warm_up',
  22: 'match',
  23: 'exercise',
  24: 'challenge',
  25: 'indoor_skiing',
  26: 'cardio_training',
  27: 'indoor_walking',
  28: 'e_bike_fitness',
  29: 'bmx',
  30: 'casual_walking',
  31: 'speed_walking',
  32: 'bike_to_run_transition',
  33: 'run_to_bike_transition',
  34: 'swim_to_bike_transition',
  35: 'atv',
  36: 'motocross',
  37: 'backcountry',
  38: 'resort',
  39: 'rc_drone',
  40: 'wingsuit',
  41: 'whitewater',
  42: 'skate_skiing',
  43: 'yoga',
  44: 'pilates',
  45: 'indoor_running',
  46: 'gravel_cycling',
  47: 'e_bike_mountain',
  48: 'commuting',
  49: 'mixed_surface',
  50: 'navigate',
  51: 'track_me',
  52: 'map',
  53: 'single_gas_diving',
  54: 'multi_gas_diving',
  55: 'gauge_diving',
  56: 'apnea_diving',
  57: 'apnea_hunting',
  58: 'virtual_activity',
  59: 'obstacle',
  254: 'all',
};

/// FIT `sport` 枚举值 → 名称（桌面端 `sport` 字段是字符串）。
const Map<int, String> kFitSportNames = {
  0: 'generic',
  1: 'running',
  2: 'cycling',
  3: 'transition',
  4: 'fitness_equipment',
  5: 'swimming',
  6: 'basketball',
  7: 'soccer',
  8: 'tennis',
  9: 'american_football',
  10: 'training',
  11: 'walking',
  12: 'cross_country_skiing',
  13: 'alpine_skiing',
  14: 'snowboarding',
  15: 'rowing',
  16: 'mountaineering',
  17: 'hiking',
  18: 'multisport',
  19: 'paddling',
  20: 'flying',
  21: 'e_biking',
  22: 'motorcycling',
  23: 'boating',
  24: 'driving',
  25: 'golf',
  26: 'hang_gliding',
  27: 'horseback_riding',
  28: 'hunting',
  29: 'fishing',
  30: 'inline_skating',
  31: 'rock_climbing',
  32: 'sailing',
  33: 'ice_skating',
  34: 'sky_diving',
  35: 'snowshoeing',
  36: 'snowmobiling',
  37: 'stand_up_paddleboarding',
  38: 'surfing',
  39: 'wakeboarding',
  40: 'water_skiing',
  41: 'kayaking',
  42: 'rafting',
  43: 'windsurfing',
  44: 'kitesurfing',
  45: 'tactical',
  46: 'jumpmaster',
  47: 'boxing',
  48: 'floor_climbing',
  254: 'all',
};

/// 数值 → FIT sub_sport 名称；未知返回 null。
String? fitSubSportName(int? value) =>
    value == null ? null : kFitSubSportNames[value];

/// 数值 → FIT sport 名称；未知返回 null。
String? fitSportName(int? value) =>
    value == null ? null : kFitSportNames[value];
