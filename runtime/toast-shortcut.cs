// Per-user shortcut identity for protocol-only desktop toast notifications.
using System;
using System.Runtime.InteropServices;

public static class FigFoxToastShortcut {
    [ComImport, Guid("00021401-0000-0000-C000-000000000046")] class ShellLink {}
    [ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IShellLinkW {
        void GetPath(IntPtr path, int max, IntPtr data, uint flags);
        void GetIDList(out IntPtr id); void SetIDList(IntPtr id);
        void GetDescription(IntPtr value, int max); void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string value);
        void GetWorkingDirectory(IntPtr value, int max); void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string value);
        void GetArguments(IntPtr value, int max); void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string value);
        void GetHotkey(out short key); void SetHotkey(short key);
        void GetShowCmd(out int show); void SetShowCmd(int show);
        void GetIconLocation(IntPtr value, int max, out int index); void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string value, int index);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string value, uint reserved);
        void Resolve(IntPtr window, uint flags); void SetPath([MarshalAs(UnmanagedType.LPWStr)] string value);
    }
    [StructLayout(LayoutKind.Sequential)] struct PropertyKey { public Guid format; public uint id; public PropertyKey(Guid f, uint i) { format=f; id=i; } }
    [StructLayout(LayoutKind.Explicit, Size=24)] struct PropVariant { [FieldOffset(0)] public ushort type; [FieldOffset(8)] public IntPtr pointer; }
    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPropertyStore {
        uint GetCount(); void GetAt(uint index, out PropertyKey key); void GetValue(ref PropertyKey key, out PropVariant value);
        void SetValue(ref PropertyKey key, ref PropVariant value); void Commit();
    }
    [ComImport, Guid("0000010B-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPersistFile {
        void GetClassID(out Guid id); [PreserveSig] int IsDirty(); void Load([MarshalAs(UnmanagedType.LPWStr)] string file, uint mode);
        void Save([MarshalAs(UnmanagedType.LPWStr)] string file, bool remember); void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string file);
        void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string file);
    }
    public static void Create(string file, string executable, string arguments, string workdir, string appid) {
        object link = new ShellLink();
        IntPtr text = Marshal.StringToCoTaskMemUni(appid), guid = Marshal.AllocCoTaskMem(16);
        try {
            IShellLinkW shell = (IShellLinkW)link;
            shell.SetPath(executable); shell.SetArguments(arguments); shell.SetWorkingDirectory(workdir); shell.SetDescription("FigFox experiment notifications"); shell.SetShowCmd(7);
            IPropertyStore store = (IPropertyStore)link;
            Guid format = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3");
            PropertyKey id = new PropertyKey(format, 5), clsid = new PropertyKey(format, 26);
            PropVariant value = new PropVariant(); value.type=31; value.pointer=text; store.SetValue(ref id, ref value);
            // Stub CLSID: only protocol activation is used. No COM server installed.
            Marshal.StructureToPtr(new Guid("B1AD1F9F-163A-43C5-A421-0A53ECB72926"), guid, false);
            value.type=72; value.pointer=guid; store.SetValue(ref clsid, ref value); store.Commit();
            ((IPersistFile)link).Save(file, true);
        } finally { Marshal.FreeCoTaskMem(text); Marshal.FreeCoTaskMem(guid); Marshal.FinalReleaseComObject(link); }
    }
}
