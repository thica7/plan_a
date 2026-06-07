#!/usr/bin/env python3
"""
Competiscope v2 (Plan A) E2E 演示自动化脚本
用于视频录制时的自动化浏览器操作和截图捕获。
"""

import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# 配置截图保存路径
SCREENSHOTS_DIR = Path("F:/platform/competition/plan_a/runs/demo-screenshots")
BASE_URL = "http://localhost:8080"


def take_screenshot(page, step_num: int, description: str, timeline: list):
    """
    捕获当前页面截图，并记录到时间线中。
    """
    # 格式化文件名：step-NN-description.png
    clean_desc = description.replace(" ", "-").lower()
    filename = f"step-{step_num:02d}-{clean_desc}.png"
    filepath = SCREENSHOTS_DIR / filename
    
    # 确保保存目录存在
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    
    # 执行截图
    page.screenshot(path=str(filepath))
    
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] 步骤 {step_num:02d}: {description} -> 保存至 {filepath.name}"
    print(log_msg)
    timeline.append(log_msg)


def set_range_value(slider, value: str):
    slider.evaluate(
        """(element, value) => {
            element.value = value;
            element.dispatchEvent(new Event('input', { bubbles: true }));
            element.dispatchEvent(new Event('change', { bubbles: true }));
        }""",
        value,
    )


def main():
    timeline = []
    print("====================================================")
    print("  Competiscope v2 (Plan A) E2E Demo Auto Runner  ")
    print("====================================================")
    
    with sync_playwright() as p:
        print("正在启动无头浏览器 (Chromium Headless)...")
        # 启动无头 Chromium 浏览器
        browser = p.chromium.launch(headless=True)
        # 设定推荐视口大小，以确保截图比例美观且一致
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        
        try:
            # 1. 导航到首页 NewRun
            print(f"正在导航至 {BASE_URL} ...")
            page.goto(BASE_URL)
            page.wait_for_load_state("networkidle")
            
            # 2. 步骤 1：输入主题并确认 Auto-discover 选中状态
            print("正在设置分析主题并确认 Auto-discover 模式...")
            # 填充 Topic 输入框
            topic_input = page.get_by_label("Topic")
            topic_input.fill("Agentic AI IDE")
            
            # 确保选中 "Auto-discover" 模式
            auto_discover_btn = page.get_by_role("button", name="Auto-discover")
            auto_discover_btn.click()
            
            # 截屏 1
            take_screenshot(page, 1, "new run topic entered", timeline)
            
            # 3. 步骤 2：启动 Run，等待 HITL Interrupt 并确认
            print("点击 'Start run' 并等待人机协同中断 (HITL Interrupt)...")
            start_run_btn = page.get_by_role("button", name="Start run")
            start_run_btn.click()
            
            # 等待编排服务运行到 planner 节点并挂起（显示 .hitl-panel 弹窗）
            # 设置较长的超时时间（如 90 秒），因为 Real API 模式下 Planner 联网搜寻竞品需要时间
            page.wait_for_selector(".hitl-panel", timeout=90000)
            
            # 截屏 2 (展示 HITL 中断计划审计状态)
            take_screenshot(page, 2, "hitl interrupt plan review", timeline)
            
            # 点击 "Continue" 按钮同意并继续运行
            print("接受分析计划，点击 'Continue' 恢复图流转...")
            continue_btn = page.get_by_role("button", name="Continue")
            continue_btn.click()
            
            # 4. 步骤 3：导航到 /crawl，等待 Frontier 抓取进度
            print("正在导航到爬虫监控页 /crawl ...")
            crawl_link = page.get_by_role("link", name="Crawl")
            crawl_link.click()
            
            # 等待 Job 队列渲染出来（即 .JobQueueTable 元素）
            page.wait_for_selector(".JobQueueTable", timeout=30000)
            
            # 稍微等待两秒，使得 Frontier 并发日志和统计图有滚动变化，效果更佳
            time.sleep(2)
            
            # 截屏 3 (展示 Frontier 抓取状态)
            take_screenshot(page, 3, "frontier crawl progress", timeline)
            
            # 5. 步骤 4：导航到 /knowledge，等待文档出现
            print("正在导航到知识库页 /knowledge ...")
            knowledge_link = page.get_by_role("link", name="Knowledge")
            knowledge_link.click()
            
            # 等待文档被爬取并 Ingest 成功进入知识库
            # 预期至少有一个 .SourceCard 文档卡片元素出现
            print("等待爬取网页被 Ingest 写入知识库...")
            page.wait_for_selector(".SourceCard", timeout=60000)
            
            # 截屏 4 (展示知识库数据实时成长)
            take_screenshot(page, 4, "knowledge base growth", timeline)
            
            # 6. 步骤 5：导航到 /search，输入查询并展示检索结果
            print("正在导航到检索页 /search ...")
            search_link = page.get_by_role("link", name="Search")
            search_link.click()
            
            # 输入检索问题
            print("输入演示 Query 并进行通用混合检索...")
            search_input = page.get_by_placeholder("Search the knowledge base...")
            search_input.fill("Compare the pricing tiers of Cursor")
            
            # 点击搜索
            search_btn = page.get_by_role("button", name="Search")
            search_btn.click()
            
            # 等待搜索结果卡片渲染出来
            page.wait_for_selector(".SourceCard", timeout=20000)
            
            # 截屏 5 (展示通用混合检索结果)
            take_screenshot(page, 5, "search results general", timeline)
            
            # 7. 步骤 6：打开检索参数抽屉，调整为 Pricing Preset，再次检索
            print("打开检索参数配置抽屉...")
            retrieval_btn = page.get_by_role("button", name="Retrieval")
            retrieval_btn.click()
            
            # 等待滑块控件加载
            page.wait_for_selector('label:has-text("Dense weight")', timeout=10000)
            
            # 更改为 Pricing 预设（调小密集向量权重，调大全文稀疏检索权重，锁定计费数字）
            print("调整参数至 Pricing 匹配预设 (Dense=0.2, Sparse=1.8)...")
            dense_slider = page.locator('label:has-text("Dense weight") input[type="range"]')
            set_range_value(dense_slider, "0.2")
            
            sparse_slider = page.locator('label:has-text("Sparse weight") input[type="range"]')
            set_range_value(sparse_slider, "1.8")
            
            # 关闭检索参数抽屉
            print("关闭参数抽屉...")
            close_btn = page.get_by_label("Close retrieval parameters")
            close_btn.click()
            
            # 再次检索以应用参数（前端 300ms 防抖，我们这里显式点击 Search 确保一致性）
            time.sleep(0.5)
            search_btn.click()
            
            # 等待新检索结果呈现
            page.wait_for_selector(".SourceCard", timeout=20000)
            
            # 截屏 6 (展示 Pricing Preset 检索结果)
            take_screenshot(page, 6, "search results pricing preset", timeline)
            
            print("\n自动化演示脚本流程运行成功！")
            
        except PlaywrightTimeoutError as e:
            print(f"\n[错误] 自动化脚本执行超时: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"\n[错误] 运行时异常: {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            # 安全清理与释放浏览器资源
            context.close()
            browser.close()
            
    # 输出时间线总结
    print("\n" + "="*20 + " 演示时间线步骤 " + "="*20)
    for event in timeline:
        print(event)
    print("="*56 + "\n")


if __name__ == "__main__":
    main()
