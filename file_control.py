import os
import subprocess


FOLDERS = {
    "desktop": os.path.join(os.path.expanduser("~"), "Desktop"),
    "documents": os.path.join(os.path.expanduser("~"), "Documents"),
    "downloads": os.path.join(os.path.expanduser("~"), "Downloads"),
    "Shadow": r"C:\Users\us448\Shadow",
}


def open_folder(folder_name):

    folder_name = folder_name.lower().strip()

    if folder_name not in FOLDERS:
        return False, f"I don't have permission to open '{folder_name}'."

    folder_path = FOLDERS[folder_name]

    if not os.path.exists(folder_path):
        return False, f"I couldn't find the {folder_name} folder."

    try:
        os.startfile(folder_path)
        return True, f"Opening {folder_name} folder."

    except Exception as error:
        return False, f"I couldn't open the folder: {error}"


def list_folder(folder_name):

    folder_name = folder_name.lower().strip()

    if folder_name not in FOLDERS:
        return False, f"I don't have permission to access '{folder_name}'."

    folder_path = FOLDERS[folder_name]

    if not os.path.exists(folder_path):
        return False, f"I couldn't find the {folder_name} folder."

    try:

        items = os.listdir(folder_path)

        if not items:
            return True, f"The {folder_name} folder is empty."

        items.sort(key=str.lower)

        result = [
            f"Contents of {folder_name}:",
            ""
        ]

        for item in items:
            full_path = os.path.join(folder_path, item)

            if os.path.isdir(full_path):
                result.append(f"[FOLDER] {item}")
            else:
                result.append(f"[FILE]   {item}")

        return True, "\n".join(result)

    except Exception as error:
        return False, f"I couldn't read the folder: {error}"


if __name__ == "__main__":

    print("Shadow FILE CONTROL")
    print("-" * 40)

    success, message = open_folder("downloads")

    print(message)

    print()

    success, message = list_folder("downloads")

    print(message)