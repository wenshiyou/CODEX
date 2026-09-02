with open('maple_route_ui.py', 'r', encoding='utf-8') as f:
    content = f.read()

route_names_methods = '''    ROUTE_NAMES_FILE = os.path.join(DATA_DIR, "route_names.json")
    MAX_ROUTES = 100

    def _load_route_names(self):
        names = {}
        if os.path.exists(self.ROUTE_NAMES_FILE):
            try:
                with open(self.ROUTE_NAMES_FILE, "r", encoding="utf-8") as f:
                    names = json.load(f)
            except Exception:
                pass
        return {str(k): v for k, v in names.items()}

    def _save_route_names(self, names):
        try:
            with open(self.ROUTE_NAMES_FILE, "w", encoding="utf-8") as f:
                json.dump(names, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print("[方案] 保存名字失败: %s" % e)

    def _get_route_name(self, route_id):
        names = self._load_route_names()
        return names.get(str(route_id), "方案%d" % route_id)

    def _set_route_name(self, route_id, name):
        names = self._load_route_names()
        names[str(route_id)] = name
        self._save_route_names(names)

'''

content = content.replace('    def _show_save_result(self, msg):', route_names_methods + '    def _show_save_result(self, msg):', 1)

with open('maple_route_ui.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('已添加方案名字相关方法')
