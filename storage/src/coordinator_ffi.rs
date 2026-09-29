//! FFI bindings to the Go Coordinator

use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_int};

extern "C" {
    fn ScatterGather(query: *const c_char, num_shards: c_int) -> *mut c_char;
    fn FreeCString(s: *mut c_char);
    fn StartBackgroundWorkers();
}

pub fn scatter_gather(query: &str, num_shards: i32) -> String {
    let c_query = CString::new(query).unwrap();
    unsafe {
        let c_res = ScatterGather(c_query.as_ptr(), num_shards);
        if c_res.is_null() {
            return String::new();
        }
        let str_res = CStr::from_ptr(c_res).to_string_lossy().into_owned();
        // Free the C string allocated by Go to prevent memory leak
        FreeCString(c_res);
        str_res
    }
}

pub fn start_background_workers() {
    unsafe {
        StartBackgroundWorkers();
    }
}
