from capability_loader import get_loader

loader = get_loader()
loader.start()
print(loader.list_loaded())