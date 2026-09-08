"""Mandatory OS caps, installed inside the disposable worker before RDF parsing."""

import sys

_job_handle = None  # Keep the Windows kill-on-close job alive for the worker lifetime.


def apply_resource_caps(
    cpu_seconds: int, memory_bytes: int, output_bytes: int, *, file_descriptors: int = 32
) -> str:
    if type(file_descriptors) is not int or not 32 <= file_descriptors <= 128:
        raise ValueError("RDF file-descriptor budget must be between 32 and 128")
    if sys.platform == "win32":
        _windows_caps(cpu_seconds, memory_bytes)
        return "WINDOWS_JOB_PROCESS_TIME_MEMORY_ACTIVE_PROCESS"
    if sys.platform == "linux":
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        resource.setrlimit(resource.RLIMIT_FSIZE, (output_bytes, output_bytes))
        resource.setrlimit(resource.RLIMIT_NOFILE, (file_descriptors, file_descriptors))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        return "LINUX_RLIMIT_CPU_AS_FSIZE_NOFILE_CORE"
    raise OSError("Required RDF resource caps are unsupported on this platform")


def _windows_caps(cpu_seconds: int, memory_bytes: int) -> None:
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_int64),
            ("job_time", ctypes.c_int64),
            ("flags", wintypes.DWORD),
            ("minimum_working_set", ctypes.c_size_t),
            ("maximum_working_set", ctypes.c_size_t),
            ("active_processes", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority_class", wintypes.DWORD),
            ("scheduling_class", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_uint64)
            for name in (
                "read_operations",
                "write_operations",
                "other_operations",
                "read_bytes",
                "write_bytes",
                "other_bytes",
            )
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("basic", BasicLimits),
            ("io", IoCounters),
            ("process_memory", ctypes.c_size_t),
            ("job_memory", ctypes.c_size_t),
            ("peak_process_memory", ctypes.c_size_t),
            ("peak_job_memory", ctypes.c_size_t),
        ]

    loader = getattr(ctypes, "WinDLL", None)
    if loader is None:
        raise OSError("RDF Windows resource-cap loader is unavailable")
    kernel = loader("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise OSError("RDF job creation failed")
    limits = ExtendedLimits()
    # PROCESS_TIME | ACTIVE_PROCESS | PROCESS_MEMORY | KILL_ON_JOB_CLOSE
    limits.basic.flags = 0x2 | 0x8 | 0x100 | 0x2000
    limits.basic.process_time = cpu_seconds * 10_000_000
    limits.basic.active_processes = 1
    limits.process_memory = memory_bytes
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        kernel.CloseHandle(job)
        raise OSError("RDF job configuration failed")
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        kernel.CloseHandle(job)
        raise OSError("RDF job assignment failed")
    global _job_handle
    _job_handle = job
