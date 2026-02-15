# DAY2.16
更新一次，中台已经搭建完毕，组织架构为：

CrawlerApp{crawler.exe,resources{backend，spiders，web},_internal}
点击exe即可使用，如需修改，只用修改spiders中对应各网站的爬虫即可










# crawler_union
目前应该实现所有爬虫代码的保存/商品初始化逻辑：
 
 1.对于商品初始化列表，建议使用：


    def get_tasks_from_file(name_file, max_count, data_dir):


    # 1. 读取原始任务列表
    try:
        if not os.path.exists(name_file):
            print(f"❌ 未找到任务文件: {name_file}")
            return []
        with open(name_file, 'r', encoding='utf-8') as f:
            names = json.load(f)
        # 去重
        product_names = list(set(names))
    except Exception as e:
        print(f"❌ 读取任务文件失败: {e}")
        return []

    # 2. 扫描现有的 JSON 文件，获取进度
    tasks_progress = {name: 0 for name in product_names}
    data_path = Path(data_dir)

    if data_path.exists():
        print(f"🔍 正在扫描 {data_dir} 目录下的断点信息...")
        for json_file in data_path.glob('*_products_*.json'):
            # 排除汇总文件
            if json_file.name.startswith('all_products'): continue

            # 解析文件名: name_products_timestamp.json
            match = re.match(r'^(.+?)_products_\d{8}_\d{6}\.json$', json_file.name)
            if not match: continue

            p_name = match.group(1)


            if p_name in tasks_progress:
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    if data and isinstance(data, list):
                        # 获取最后一条数据的 index 作为当前进度
                        # 假设每条数据都有 'index' 字段，如果没有则使用列表长度
                        last_item = data[-1]

                        current  = int(last_item.get('page', 0))
                        if not current:
                            current = int(last_item.get('index', len(data)))

                        # 更新最大进度（防止有多个旧文件，取最大的那个）
                        if current > tasks_progress[p_name]:
                            tasks_progress[p_name] = current
                except Exception as e:
                    print(f"  ⚠️ 读取文件 {json_file.name} 失败: {e}")
                    continue

    # 3. 生成最终任务列表
    final_tasks = []
    for name, progress in tasks_progress.items():
        if progress < max_count:
            if progress > 0:
                print(f"  🔄 恢复任务: {name} (从 {progress} 开始)")
            final_tasks.append((name, progress))
        else:
            # print(f"  ✅ 跳过已完成: {name}") # 可选：打印已完成的任务
            pass

    # 按名称排序，保证每次运行顺序一致
    return sorted(final_tasks, key=lambda x: x[0])

    对于无限滚动翻页的网站，直接使用商品编号index作为断点
    对于翻页网站，使用page作为断点


2.对于商品保存，建议使用：

        def _save_data(self, product_name, new_data, start_index, output_dir):

        """通用保存数据辅助函数：支持索引合并与页码合并"""
        
        final_data = new_data
        files_to_remove = []
        
        # 1. 预处理文件名逻辑（eBay关键词可能包含特殊字符，需与任务获取逻辑一致）
        
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", product_name)[:50]
        if start_index > 0:
            print(f"\n🔄 [合并模式] 检测到续传 (起始标记 {start_index})，检索旧文件...")
            try:
                from pathlib import Path
                data_path = Path(output_dir)
                candidate_files = []
                
                # 使用清洗后的文件名进行搜索
                
                for f in data_path.glob(f'{safe_name}_products_*.json'):
                    candidate_files.append(f)
                
                candidate_files.sort(key=lambda x: x.name, reverse=True)

                if candidate_files:
                    latest_json = candidate_files[0]
                    with open(latest_json, 'r', encoding='utf-8') as f:
                        old_data = json.load(f)

                    if isinstance(old_data, list) and len(old_data) > 0:
                        # --- 核心改进：检测逻辑类型 ---
                        # 检查第一条数据是否有 'page' 字段
                        is_page_logic = 'page' in old_data[0]

                        if is_page_logic:
                            # 翻页逻辑：start_index 此时代表的是 max_page
                            # 我们不做长度强校验，因为每页数量可能不固定
                            print(f"    📄 检测到 [翻页逻辑]，上次爬取至第 {start_index} 页")
                        else:
                            # 无限滚动逻辑：校验长度
                            if len(old_data) != start_index:
                                print(f"    ⚠️ 警告: 旧数据长度 ({len(old_data)}) 与 start_index ({start_index}) 不一致")
                        
                        # 合并数据
                        final_data = old_data + new_data
                        print(f"    ➕ 合并成功: 旧({len(old_data)}) + 新({len(new_data)}) = 总({len(final_data)})")
                        
                        # 记录待删除旧文件
                        files_to_remove.append(latest_json)
                        old_csv = latest_json.with_suffix('.csv')
                        if old_csv.exists(): 
                            files_to_remove.append(old_csv)
                else:
                    print("    ⚠️ 未找到旧文件，将作为新任务保存")
            except Exception as e:
                print(f"    ❌ 合并出错: {e}")

        # 2. 持久化新数据
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        new_json_name = os.path.join(output_dir, f"{safe_name}_products_{timestamp}.json")
        new_csv_name = os.path.join(output_dir, f"{safe_name}_products_{timestamp}.csv")

        if not os.path.exists(output_dir): 
            os.makedirs(output_dir)

        # 保存 JSON
        with open(new_json_name, 'w', encoding='utf-8') as f:
            json.dump(final_data, f, ensure_ascii=False, indent=2)
        print(f"💾 JSON保存: {os.path.basename(new_json_name)}")

        # 保存 CSV
        import csv
        if final_data:
            with open(new_csv_name, 'w', encoding='utf-8', newline='') as f:
                keys = final_data[0].keys()
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(final_data)
            print(f"💾 CSV保存: {os.path.basename(new_csv_name)}")

        # 3. 清理陈旧文件
        if files_to_remove:
            print(f"🧹 清理旧版本文件...")
            for f in files_to_remove:
                try:
                    os.remove(f)
                    print(f"    🗑️ 删除: {f.name}")
                except Exception as e:
                    print(f"    ⚠️ 无法删除旧文件 {f.name}: {e}")
        统一使用这个函数来确保合并数据时的鲁棒性



  3.传入逻辑：
  对于滚动式网站，输入初始index，来跳过前index个数据，对于翻页式，则跳过前index页开始爬取
