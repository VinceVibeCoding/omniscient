//! One Omnigroup at a time. A second launch (a click on the pinned taskbar icon, or on the
//! Start menu entry) asks the running widget to show itself, then quits.
//!
//! The first instance owns a loopback port. A second one finds it taken, says hello and, if
//! the owner answers, exits. If something else holds the port (no answer), we start anyway:
//! a stranger on that port must never stop Omnigroup from opening. Standard library only.

use std::io::{BufRead, BufReader, Read, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::thread;
use std::time::Duration;

const PORT: u16 = 47_322;
const HELLO: &str = "omnigroup-show";
const REPLY: &str = "omnigroup-ok";
const TIMEOUT: Duration = Duration::from_millis(1500);
/// Longest line read from a client: a local process can't make us buffer more.
const MAX_LINE: u64 = 64;

pub enum Role {
    /// We are the widget. The listener is `None` when the port is held by something else.
    Primary(Option<TcpListener>),
    /// Another Omnigroup answered: it was asked to show itself, we quit.
    Secondary,
}

pub fn claim() -> Role {
    claim_at(SocketAddr::from((Ipv4Addr::LOCALHOST, PORT)))
}

pub fn claim_at(addr: SocketAddr) -> Role {
    match TcpListener::bind(addr) {
        Ok(listener) => Role::Primary(Some(listener)),
        Err(_) if ask_running(addr) => Role::Secondary,
        Err(err) => {
            eprintln!("omnigroup: single-instance port unavailable ({err}); starting anyway");
            Role::Primary(None)
        }
    }
}

fn ask_running(addr: SocketAddr) -> bool {
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, TIMEOUT) else { return false };
    if stream.set_read_timeout(Some(TIMEOUT)).is_err()
        || writeln!(stream, "{HELLO}").is_err()
    {
        return false;
    }
    let mut line = String::new();
    BufReader::new(stream.take(MAX_LINE)).read_line(&mut line).is_ok() && line.trim() == REPLY
}

/// Answers second launches on a thread of its own; `on_show` runs for each valid hello.
pub fn serve<F>(listener: TcpListener, on_show: F)
where
    F: Fn() + Send + 'static,
{
    thread::spawn(move || {
        for connection in listener.incoming() {
            match connection {
                Ok(stream) => answer(stream, &on_show),
                Err(err) => eprintln!("omnigroup: single-instance accept failed: {err}"),
            }
        }
    });
}

fn answer<F: Fn()>(mut stream: TcpStream, on_show: &F) {
    if stream.set_read_timeout(Some(TIMEOUT)).is_err() {
        return;
    }
    let mut line = String::new();
    let read = BufReader::new((&stream).take(MAX_LINE)).read_line(&mut line);
    if read.is_err() || line.trim() != HELLO {
        return;
    }
    if writeln!(stream, "{REPLY}").is_ok() {
        on_show();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::mpsc;

    fn free_addr() -> SocketAddr {
        let probe = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).expect("probe port");
        probe.local_addr().expect("probe address")
    }

    #[test]
    fn a_second_launch_asks_the_first_to_show_and_quits() {
        let addr = free_addr();
        let Role::Primary(Some(listener)) = claim_at(addr) else { panic!("first launch must own the port") };
        let (tx, rx) = mpsc::channel();
        serve(listener, move || tx.send(()).expect("receiver alive"));
        assert!(matches!(claim_at(addr), Role::Secondary));
        rx.recv_timeout(Duration::from_secs(2)).expect("the first instance was asked to show");
    }

    #[test]
    fn a_second_launch_gets_its_answer_even_when_the_show_callback_is_slow() {
        // The first instance answers at once and shows the window later: a second launch must not
        // time out while the first is still starting up.
        let addr = free_addr();
        let Role::Primary(Some(listener)) = claim_at(addr) else { panic!("first launch must own the port") };
        serve(listener, || std::thread::sleep(Duration::from_secs(3)));
        let started = std::time::Instant::now();
        assert!(matches!(claim_at(addr), Role::Secondary));
        assert!(started.elapsed() < Duration::from_millis(1200));
    }

    #[test]
    fn a_stranger_holding_the_port_does_not_stop_us() {
        let addr = free_addr();
        let _stranger = TcpListener::bind(addr).expect("stranger binds"); // never answers
        assert!(matches!(claim_at(addr), Role::Primary(None)));
    }

    #[test]
    fn a_wrong_greeting_shows_nothing() {
        let addr = free_addr();
        let Role::Primary(Some(listener)) = claim_at(addr) else { panic!("first launch must own the port") };
        let (tx, rx) = mpsc::channel();
        serve(listener, move || tx.send(()).expect("receiver alive"));
        let mut stream = TcpStream::connect(addr).expect("connect");
        writeln!(stream, "hello there").expect("write");
        assert!(rx.recv_timeout(Duration::from_millis(400)).is_err());
    }
}
