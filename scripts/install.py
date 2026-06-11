#!/usr/bin/env python3
"""
智能排班系统 v3.0 - 一键安装脚本

目标 Agent 收到技能包后，只需执行此脚本即可自动完成：
1. 提取应用配置（自动生成 config.json）
2. 输出管道创建指令

用法:
    python install.py --app-id YOUR_APP_ID --api-key YOUR_API_KEY
"""

import json
import sys
import argparse
from pathlib import Path

# 添加 scripts 目录到路径
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from init_config import ConfigInitializer


def print_step(step, title):
    print(f"\n{'='*60}")
    print(f"步骤 {step}: {title}")
    print(f"{'='*60}")


def run_init_config(app_id, api_key):
    """运行初始化脚本提取配置"""
    print_step(1, "提取应用配置")

    initializer = ConfigInitializer(app_id, api_key)
    config = initializer.build_config()

    if not config:
        print("ERROR: 配置生成失败", file=sys.stderr)
        return False

    # 验证
    print("\n验证配置...")
    is_valid = initializer.validate_config(config)

    # 保存
    output_path = SCRIPT_DIR.parent / "config.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 配置已保存: {output_path}")

    if not is_valid:
        print("⚠️  配置验证有警告，请检查上方输出")

    return True


def show_pipeline_instructions():
    """输出管道创建指令"""
    print_step(2, "创建自动化管道")

    meta_path = SCRIPT_DIR.parent / "pipelines" / "pipelines-meta.json"
    if not meta_path.exists():
        print("❌ 管道元配置不存在")
        return False

    with open(meta_path, 'r', encoding='utf-8') as f:
        meta = json.load(f)

    print(f"找到 {len(meta['pipelines'])} 个管道配置：\n")

    for pipeline in meta['pipelines']:
        task_design_path = SCRIPT_DIR.parent / pipeline['task_design_file']
        print(f"📋 管道: {pipeline['display_name']}")
        print(f"   触发方式: {pipeline['trigger_config']['type']}")
        if task_design_path.exists():
            print(f"   任务设计: {task_design_path}")
        print()

    print("请让 Agent 读取 pipelines-meta.json 并调用 automation(action='create') 创建管道。")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="智能排班系统 v3.0 一键安装",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python install.py --app-id 6a27a51042f13fb09f36ce8d --api-key YOUR_API_KEY
        """
    )

    parser.add_argument("--app-id", required=True, help="简道云应用 ID")
    parser.add_argument("--api-key", required=True, help="简道云 API Key")

    args = parser.parse_args()

    print("=" * 60)
    print("智能排班系统 v3.0 - 安装")
    print("=" * 60)

    # 步骤 1: 提取配置
    if not run_init_config(args.app_id, args.api_key):
        sys.exit(1)

    # 步骤 2: 输出管道指令
    if not show_pipeline_instructions():
        sys.exit(1)

    print("\n" + "=" * 60)
    print("安装完成！")
    print("=" * 60)
    print("\n下一步：")
    print("  1. 让 Agent 读取 SKILL.md 了解系统架构")
    print("  2. 让 Agent 读取 pipelines-meta.json 创建两个自动化管道")
    print("  3. 将请假管道的 Webhook URL 配置到简道云请假表")
    print(f"\n配置文件: {SCRIPT_DIR.parent / 'config.json'}")


if __name__ == "__main__":
    main()
