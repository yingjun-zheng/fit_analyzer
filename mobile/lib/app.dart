import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// 应用根。
///
/// P0 阶段只跑通骨架；实际页面在 P3/P4 接入。
class FitAnalyzerApp extends StatelessWidget {
  const FitAnalyzerApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ProviderScope(
      child: MaterialApp(
        title: 'fit_analyzer',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          useMaterial3: true,
          colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF185FA5)),
        ),
        home: const _BootstrapPage(),
      ),
    );
  }
}

/// 启动页：显示 P0/P1 完成情况，兼作自检面板。
class _BootstrapPage extends StatelessWidget {
  const _BootstrapPage();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('fit_analyzer mobile')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: const [
          _Section(
            title: 'P0 骨架',
            done: true,
            items: ['Flutter 项目结构', '依赖配置（pubspec.yaml）'],
          ),
          _Section(
            title: 'P1 统计算法（照抄桌面端口径）',
            done: true,
            items: [
              '爬升/下降（滞回参考点法）',
              '移动时间',
              '区间时间加权（速度/心率/踏频/功率）',
              '曲线抽稀 / 轨迹抽稀',
              '按公里分桶',
              'NP / TSS / CTL / ATL / TSB',
              '月度 / 年度 / 趋势 / 个人纪录',
              '估算功率（物理模型）',
            ],
          ),
          _Section(
            title: '待办',
            done: false,
            items: [
              'FIT 解析适配层（activity_files → ActivityRecord）',
              'drift 数据库',
              '本地文件导入',
              '活动列表 / 单次深度分析',
              '月度 / 年度 / 趋势页面',
              '多平台数据源',
              'AI 分析',
            ],
          ),
        ],
      ),
    );
  }
}

class _Section extends StatelessWidget {
  final String title;
  final bool done;
  final List<String> items;

  const _Section({
    required this.title,
    required this.done,
    required this.items,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  done ? Icons.check_circle : Icons.radio_button_unchecked,
                  size: 20,
                  color: done ? Colors.green : theme.colorScheme.outline,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(title, style: theme.textTheme.titleMedium),
                ),
              ],
            ),
            const SizedBox(height: 8),
            for (final item in items)
              Padding(
                padding: const EdgeInsets.only(left: 28, top: 4),
                child: Text('· $item', style: theme.textTheme.bodyMedium),
              ),
          ],
        ),
      ),
    );
  }
}
